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

from app.core.consultation_state import ConsultationStep, can_transition
from app.core.deps import get_current_user
from app.core.exceptions import ConsultationError, PermissionDeniedError
from app.models.base import get_db
from app.models.consultation import Consultation
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.consultation import (
    ChatTurnResponse,
    ConclusionResponse,
    ConfirmReportResponse,
    ConsultationCreate,
    ConsultationListResponse,
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


@router.get("", response_model=ConsultationListResponse)
async def list_my_consultations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    scenario: str | None = None,
    status_filter: str | None = None,
    limit: int = 20,
) -> ConsultationListResponse:
    """我的问诊列表（跨项目，按更新时间倒序）。

    用于 Dashboard「最近问诊」与未来的「场景中心」页。
    """
    stmt = (
        select(Consultation)
        .where(Consultation.user_id == user.id)
        .options(
            selectinload(Consultation.conclusions),
            selectinload(Consultation.facts),
            selectinload(Consultation.project),
        )
        .order_by(Consultation.updated_at.desc())
        .limit(limit)
    )
    if scenario:
        stmt = stmt.where(Consultation.scenario == scenario)
    if status_filter:
        stmt = stmt.where(Consultation.status == status_filter)

    rows = (await db.execute(stmt)).scalars().all()
    items = [
        consultation_engine.to_list_item(
            c, c.project.name if c.project else None
        )
        for c in rows
    ]
    return ConsultationListResponse(items=items, total=len(items))


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

    role 取自项目（project.role），而非用户。
    """
    consultation = await _get_consultation(db, consultation_id, user)
    project = await db.get(Project, consultation.project_id)
    if project is None:
        raise ConsultationError(f"项目不存在: {consultation.project_id}")
    project_role = UserRole(project.role)

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            async for event in consultation_engine.stream_report(
                db, consultation, user=project_role
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
    facts = list(c.facts)
    state = c.state_data or {}
    warnings = state.get("evidence_warnings") or []
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
        facts=[FactResponse.model_validate(f) for f in facts],
        conclusions=[ConclusionResponse.model_validate(x) for x in c.conclusions],
        fact_progress=consultation_engine.build_fact_progress(
            facts, consultation_engine.pending_from_state(state)
        ),
        evidence_warnings=warnings if isinstance(warnings, list) else [],
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
        current_step=result["current_step"],
        new_fact_labels=result["new_fact_labels"],
        pending_facts=result["pending_facts"],
        fact_progress=result["fact_progress"],
        extraction_error=result["extraction_error"],
    )


@router.post(
    "/{consultation_id}/confirm",
    response_model=ConfirmReportResponse,
)
async def confirm_report(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfirmReportResponse:
    """用户确认生成报告（状态机迁移 #6：awaiting_confirm → generating_report）。

    与 generate-report-stream 的分工：
    - 本端点只做**状态迁移与校验**，让"用户确认"这个动作在状态机里留痕，
      并能在状态不对时明确拒绝（如已生成过）。
    - 实际的 LLM 流式生成仍走 generate-report-stream。

    consultation-ui.md §5.1 允许必填未齐时提前生成：此时不阻断，
    但在响应里返回 missing_required，由前端提示。
    """
    consultation = await _get_consultation(db, consultation_id, user)
    current = consultation.current_step or ConsultationStep.INIT.value

    if current == ConsultationStep.DONE.value:
        raise ConsultationError("本次问诊已生成报告，如需继续请新建问诊")
    if current in (
        ConsultationStep.GENERATING_REPORT.value,
        ConsultationStep.GENERATING_ARTIFACTS.value,
    ):
        # 已在生成中，幂等返回，避免用户连点造成重复生成
        return ConfirmReportResponse(
            consultation_id=consultation.id,
            current_step=current,
            ready_to_report=True,
        )
    if not can_transition(current, ConsultationStep.GENERATING_REPORT.value):
        raise ConsultationError(f"当前状态（{current}）不允许生成报告")

    consultation.current_step = ConsultationStep.GENERATING_REPORT.value
    await db.commit()

    facts = await consultation_engine.load_facts(db, consultation.id)
    progress = consultation_engine.build_fact_progress(facts)
    return ConfirmReportResponse(
        consultation_id=consultation.id,
        current_step=consultation.current_step,
        ready_to_report=not progress.missing_required,
        missing_required=progress.missing_required,
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
