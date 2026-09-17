"""问诊路由：合同审查场景的核心端到端流程。

W1 端点：
- POST   /consultations                       创建问诊
- POST   /consultations/{id}/submit-text      提交合同文本
- POST   /consultations/{id}/generate-report  生成审查报告（Mock LLM）
- GET    /consultations/{id}                  问诊详情（含 facts + conclusions）
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.core.exceptions import ConsultationError, PermissionDeniedError
from app.models.base import get_db
from app.models.consultation import Consultation
from app.models.user import User, UserRole
from app.schemas.consultation import (
    ChatTurnResponse,
    ConclusionResponse,
    ConsultationCreate,
    ConsultationMessageCreate,
    ConsultationMessageResponse,
    ConsultationResponse,
    FactResponse,
    GenerateReportResponse,
    SubmitTextRequest,
)
from app.services import consultation_engine

router = APIRouter(prefix="/consultations", tags=["consultations"])


async def _get_consultation(
    db: AsyncSession, consultation_id: int, user: User
) -> Consultation:
    """获取问诊（要求当前用户是创建者）。"""
    stmt = (
        select(Consultation)
        .where(Consultation.id == consultation_id)
        .options(
            selectinload(Consultation.facts),
            selectinload(Consultation.conclusions),
        )
    )
    result = await db.execute(stmt)
    consultation = result.scalar_one_or_none()
    if consultation is None:
        raise ConsultationError(f"问诊不存在: {consultation_id}")
    if consultation.user_id != user.id:
        raise PermissionDeniedError("无权访问该问诊")
    return consultation


@router.post("", response_model=ConsultationResponse, status_code=status.HTTP_201_CREATED)
async def create_consultation(
    req: ConsultationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConsultationResponse:
    """创建问诊会话。"""
    consultation = await consultation_engine.create_consultation(
        db,
        project_id=req.project_id,
        user_id=user.id,
        scenario=req.scenario,
    )
    await db.refresh(consultation, attribute_names=["facts", "conclusions"])
    return _to_response(consultation)


@router.post(
    "/{consultation_id}/submit-text",
    response_model=ConsultationResponse,
)
async def submit_text(
    consultation_id: int,
    req: SubmitTextRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConsultationResponse:
    """提交合同文本（W1：纯文本）。"""
    consultation = await _get_consultation(db, consultation_id, user)
    await consultation_engine.submit_contract_text(
        db, consultation, req.content, user=user
    )
    await db.refresh(consultation, attribute_names=["facts", "conclusions"])
    return _to_response(consultation)


@router.post(
    "/{consultation_id}/generate-report",
    response_model=GenerateReportResponse,
)
async def generate_report(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GenerateReportResponse:
    """生成合同审查报告（Mock LLM）。"""
    consultation = await _get_consultation(db, consultation_id, user)
    report = await consultation_engine.generate_report(
        db, consultation, user=user
    )

    # 重新加载以拿到刚写入的 conclusions
    await db.refresh(consultation, attribute_names=["conclusions"])

    return GenerateReportResponse(
        consultation_id=consultation.id,
        status=consultation.status,
        summary=report["summary"],
        conclusions=[
            ConclusionResponse.model_validate(c) for c in consultation.conclusions
        ],
        disclaimer=report["disclaimer"],
    )


@router.post("/{consultation_id}/generate-report-stream")
async def generate_report_stream(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """流式生成合同审查报告（真实 LLM）。

    返回 application/x-ndjson 流，每行一个 JSON dict：
    - {"type": "chunk", "text": "..."}  - LLM 输出片段
    - {"type": "done", "summary": "...", "risk_count": N}  - 完成
    - {"type": "error", "message": "..."}  - 错误
    """
    consultation = await _get_consultation(db, consultation_id, user)

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            async for event in consultation_engine.stream_report(
                db, consultation, user=UserRole(user.role)
            ):
                line = json.dumps(event, ensure_ascii=False) + "\n"
                yield line.encode("utf-8")
        except Exception as e:  # noqa: BLE001
            err = json.dumps(
                {"type": "error", "message": str(e)}, ensure_ascii=False
            )
            yield (err + "\n").encode("utf-8")

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
    )


@router.get("/{consultation_id}", response_model=ConsultationResponse)
async def get_consultation(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConsultationResponse:
    """问诊详情。"""
    consultation = await _get_consultation(db, consultation_id, user)
    return _to_response(consultation)


def _to_response(c: Consultation) -> ConsultationResponse:
    return ConsultationResponse(
        id=c.id,
        project_id=c.project_id,
        scenario=c.scenario,
        status=c.status,
        dispute_summary_user=c.dispute_summary_user,
        dispute_summary_ai=c.dispute_summary_ai,
        current_step=c.current_step,
        created_at=c.created_at,
        updated_at=c.updated_at,
        facts=[FactResponse.model_validate(f) for f in c.facts],
        conclusions=[ConclusionResponse.model_validate(c) for c in c.conclusions],
    )


# ===== 多轮对话端点（W2-Phase1A）=====


@router.post(
    "/{consultation_id}/messages",
    response_model=ChatTurnResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    consultation_id: int,
    req: ConsultationMessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatTurnResponse:
    """发送一条消息，AI 回复后返回完整对话轮。

    非流式（流式在 W2-Phase1B 引入 EventSource）。
    """
    consultation = await _get_consultation(db, consultation_id, user)
    result = await consultation_engine.chat_turn(
        db, consultation, user_content=req.content
    )
    return ChatTurnResponse(
        consultation_id=consultation.id,
        user_message_id=result["user_message_id"],
        assistant_message_id=result["assistant_message_id"],
        assistant_content=result["assistant_content"],
        ready_to_report=result["ready_to_report"],
        fact_count=result["fact_count"],
    )


@router.get(
    "/{consultation_id}/messages",
    response_model=list[ConsultationMessageResponse],
)
async def list_messages(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ConsultationMessageResponse]:
    """获取问诊所有消息（按时间排序）。"""
    await _get_consultation(db, consultation_id, user)

    from app.models.consultation import ConsultationMessage

    result = await db.execute(
        select(ConsultationMessage)
        .where(ConsultationMessage.consultation_id == consultation_id)
        .order_by(ConsultationMessage.created_at)
    )
    return [
        ConsultationMessageResponse.model_validate(m)
        for m in result.scalars().all()
    ]
