"""问诊引擎：编排"合同审查"场景的核心流程。

W1 流程（合同审查场景）：
    1. 收集用户输入的合同文本
    2. 创建/获取 Consultation
    3. 调用 llm_mock 生成报告
    4. 存储事实 + 结论到数据库
    5. 返回 GenerateReportResponse
"""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DISCLAIMER
from app.core.exceptions import ConsultationError
from app.models.consultation import (
    Consultation,
    ConsultationConclusion,
    ConsultationFact,
    ConsultationMessage,
    ConsultationScenario,
    ConsultationStatus,
)
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.consultation import ConsultationListItem
from app.services.llm import LLMMessage, LLMTaskType, get_llm_client
from app.services.llm_mock import generate_contract_review_report


async def _resolve_project_role(db: AsyncSession, consultation: Consultation) -> UserRole:
    """从 consultation 拿到所属项目的 role（LLM 视角依据）。"""
    project = await db.get(Project, consultation.project_id)
    if project is None:
        raise ConsultationError(f"项目不存在: {consultation.project_id}")
    return UserRole(project.role)


async def submit_contract_text(
    db: AsyncSession,
    consultation: Consultation,
    content: str,
    *,
    user: User,
) -> ConsultationFact:
    """用户提交合同文本 - 写入事实卡片。

    简化：每个用户输入存一条 fact (fact_key="contract_text")。
    """
    if consultation.status != ConsultationStatus.IN_PROGRESS:
        raise ConsultationError(f"问诊已结束（{consultation.status}），不能继续提交")

    fact = ConsultationFact(
        consultation_id=consultation.id,
        fact_key="contract_text",
        fact_label="合同条款文本",
        fact_value=content,
        fact_value_type="text",
        source_type="user_input",
        confidence=1.0,
    )
    db.add(fact)
    await db.flush()
    return fact


async def generate_report(
    db: AsyncSession,
    consultation: Consultation,
    *,
    user: User,
) -> dict[str, Any]:
    """生成合同审查报告（Mock LLM）。

    流程：
    - 取最近一次合同文本作为输入
    - 调 llm_mock
    - 写结论到 DB
    - 标记问诊 completed
    - 返回响应数据
    """
    # 1. 取合同文本
    contract_text = ""
    for fact in reversed(consultation.facts):
        if fact.fact_key == "contract_text":
            contract_text = fact.fact_value
            break

    if not contract_text:
        raise ConsultationError("未找到合同文本，请先调用 submit-text")

    # 2. role 取自项目（用户在本项目里的角色），非 user.role
    role = await _resolve_project_role(db, consultation)
    report = generate_contract_review_report(
        contract_text=contract_text,
        role=role,
    )

    # 3. 写结论
    for c in report["conclusions"]:
        conclusion = ConsultationConclusion(
            consultation_id=consultation.id,
            level=c["level"],
            title=c["title"],
            content=c["content"],
            fact_refs=c.get("fact_refs", []),
            law_refs=c.get("law_refs", []),
            standard_refs=c.get("standard_refs", []),
            reasoning_chain=c.get("reasoning_chain"),
            counter_arguments=c.get("counter_arguments"),
        )
        db.add(conclusion)

    # 4. 更新状态
    consultation.status = ConsultationStatus.COMPLETED.value
    consultation.dispute_summary_ai = report["summary"]

    await db.flush()
    return report


async def create_consultation(
    db: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    scenario: ConsultationScenario,
) -> Consultation:
    """创建问诊会话。"""
    consultation = Consultation(
        project_id=project_id,
        user_id=user_id,
        scenario=scenario.value,
        status=ConsultationStatus.IN_PROGRESS.value,
        current_step="await_text",
    )
    db.add(consultation)
    await db.flush()
    return consultation


def to_list_item(
    c: Consultation, project_name: str | None = None
) -> ConsultationListItem:
    """Consultation ORM -> 列表项（含红黄绿计数）。

    调用前请确保 conclusions / facts 已 eager load，否则会触发懒加载。
    """
    red = sum(1 for x in c.conclusions if x.level == "red")
    yellow = sum(1 for x in c.conclusions if x.level == "yellow")
    green = sum(1 for x in c.conclusions if x.level == "green")
    return ConsultationListItem(
        id=c.id,
        project_id=c.project_id,
        project_name=project_name,
        scenario=c.scenario,
        status=c.status,
        summary=c.dispute_summary_ai,
        fact_count=len(c.facts),
        conclusion_count=len(c.conclusions),
        red_count=red,
        yellow_count=yellow,
        green_count=green,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ===== 多轮对话 =====


async def chat_turn(
    db: AsyncSession,
    consultation: Consultation,
    *,
    user_content: str,
) -> dict[str, Any]:
    """处理一轮对话：保存用户消息 → LLM 流式生成助手回复 → 保存助手消息。

    返回：{
        "user_message_id": int,
        "assistant_message_id": int,
        "assistant_content": str,  # 完整内容
        "ready_to_report": bool,
        "fact_count": int,
        "new_fact_labels": list[str],  # 本轮识别的事实类型
    }
    """
    # 1. 保存用户消息
    user_msg = ConsultationMessage(
        consultation_id=consultation.id,
        role="user",
        content=user_content,
        step_at_time=consultation.current_step,
    )
    db.add(user_msg)
    await db.flush()

    # 2. 加载上下文
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.services.chat import (
        build_chat_messages,
        extract_fact_labels,
        is_information_sufficient,
        search_laws,
    )

    # 2a. 重新查询 consultation 拿 messages
    result = await db.execute(
        select(Consultation)
        .options(
            selectinload(Consultation.messages),
            selectinload(Consultation.facts),
        )
        .where(Consultation.id == consultation.id)
    )
    consultation_full = result.scalar_one()

    # 2b. 知识库检索（用用户输入做关键词）
    knowledge_hits = await search_laws(db, user_content, limit=3)

    # 2c. role 取自项目（用户在本项目里的角色），非 user.role
    role = await _resolve_project_role(db, consultation)
    msgs = build_chat_messages(
        role=role,
        scenario=consultation.scenario,
        facts=list(consultation_full.facts),
        knowledge_hits=knowledge_hits,
        recent_messages=list(consultation_full.messages),
        new_user_content=user_content,
    )

    # 3. LLM 流式生成
    from app.services.llm import LLMMessage, LLMTaskType, get_llm_client

    client = get_llm_client()
    chunks: list[str] = []
    try:
        async for piece in client.stream_chat(
            task=LLMTaskType.CONSULTATION_REASONING,
            messages=[
                LLMMessage(role=m["role"], content=m["content"]) for m in msgs
            ],
            temperature=1.0,
            max_tokens=2000,
            json_mode=False,
        ):
            chunks.append(piece)
    except Exception as e:  # noqa: BLE001
        full_content = f"⚠️ LLM 调用失败: {e}"
    else:
        full_content = "".join(chunks)

    # 4. 保存助手消息
    assistant_msg = ConsultationMessage(
        consultation_id=consultation.id,
        role="assistant",
        content=full_content,
        step_at_time=consultation.current_step,
    )
    db.add(assistant_msg)
    await db.flush()

    # 5. 抽取新事实标签（写入 fact 卡片）
    new_fact_labels = extract_fact_labels(user_content)
    base_count = len(consultation_full.facts)
    for i, label in enumerate(new_fact_labels):
        fact = ConsultationFact(
            consultation_id=consultation.id,
            fact_key=f"chat_turn_{base_count + i}",
            fact_label=label,
            fact_value=user_content[:500],  # 摘要
            fact_value_type="text",
            source_type="user_input",
            source_message_id=user_msg.id,
            confidence=0.8,  # 启发式抽取，置信度低一些
        )
        db.add(fact)
    await db.flush()

    # 6. 判断是否信息充分
    all_messages = sorted(consultation_full.messages, key=lambda m: m.created_at)
    ready = is_information_sufficient(
        fact_count=len(consultation_full.facts) + len(new_fact_labels),
        last_messages=all_messages + [user_msg, assistant_msg],
    )

    return {
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
        "assistant_content": full_content,
        "ready_to_report": ready,
        "fact_count": len(consultation_full.facts) + len(new_fact_labels),
        "new_fact_labels": new_fact_labels,
    }


# ===== 流式输出 =====


async def stream_report(
    db: AsyncSession,
    consultation: Consultation,
    *,
    user: UserRole,
    contract_text: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式生成合同审查报告。

    每个 yield 是一个 dict，包含：
    - {"type": "chunk", "text": "..."}  - LLM 输出片段（增量）
    - {"type": "conclusion", "title": ..., "level": ..., ...}  - 单条结论
    - {"type": "done", "summary": "..."}  - 完成
    - {"type": "error", "message": "..."}  - 出错

    流结束时一次性把结论写入 DB。
    """
    client = get_llm_client()

    # 用 chat.py 的 build_report_messages（合并所有 messages + facts）
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.services.chat import build_report_messages, search_laws

    # 重新加载 consultation（含 messages + facts）
    result = await db.execute(
        select(Consultation)
        .options(
            selectinload(Consultation.messages),
            selectinload(Consultation.facts),
        )
        .where(Consultation.id == consultation.id)
    )
    consultation_full = result.scalar_one()

    # 兼容两条路径：
    #   1) 一次性提交（submit-text → fact_key="contract_text"）
    #   2) 多轮对话（chat_turn → messages + 自动抽取的 facts）
    # 只要有任一来源即可生成报告。
    if contract_text is None:
        for fact in consultation_full.facts:
            if fact.fact_key == "contract_text":
                contract_text = fact.fact_value
                break

    has_messages = len(consultation_full.messages) > 0
    has_facts = len(consultation_full.facts) > 0
    if not contract_text and not has_messages and not has_facts:
        yield {
            "type": "error",
            "message": "尚无任何事实信息，请先提交合同文本或与 AI 对话补充事实",
        }
        return

    # 知识库检索：合同文本 + 所有 facts + 最近对话
    search_parts: list[str] = []
    if contract_text:
        search_parts.append(contract_text)
    search_parts.extend(f.fact_value for f in consultation_full.facts)
    search_parts.extend(m.content for m in consultation_full.messages[-4:])
    search_text = " ".join(search_parts)
    knowledge_hits = await search_laws(db, search_text, limit=5)

    messages = build_report_messages(
        role=user,
        scenario=consultation.scenario,
        facts=list(consultation_full.facts),
        knowledge_hits=knowledge_hits,
        all_messages=list(consultation_full.messages),
    )

    # 缓冲完整内容（流式收完后一次性解析）
    chunks: list[str] = []
    try:
        async for piece in client.stream_chat(
            task=LLMTaskType.CONSULTATION_REASONING,
            messages=[
                LLMMessage(role=m["role"], content=m["content"]) for m in messages
            ],
            temperature=1.0,
            max_tokens=8000,
            json_mode=True,  # JSON Schema + 禁用 thinking
        ):
            chunks.append(piece)
            yield {"type": "chunk", "text": piece}
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"LLM 调用失败: {e}"}
        return

    full_content = "".join(chunks)

    # 鲁棒提取 JSON（M3 thinking 模式可能不闭合 <think> 标签）
    json_match = re.search(r"\{.*\}", full_content, re.DOTALL)
    if not json_match:
        yield {"type": "error", "message": "模型未输出 JSON"}
        return
    json_text = json_match.group(0)

    try:
        report = json.loads(json_text)
    except json.JSONDecodeError as e:
        yield {"type": "error", "message": f"JSON 解析失败: {e}"}
        return

    # 写结论到 DB
    for c in report.get("risks", []):
        conclusion = ConsultationConclusion(
            consultation_id=consultation.id,
            level=c.get("level", "yellow"),
            title=c.get("clause", "未命名风险"),
            content=c.get("reason", ""),
            law_refs=[],
            standard_refs=[],
        )
        db.add(conclusion)

    consultation.status = ConsultationStatus.COMPLETED.value
    consultation.dispute_summary_ai = report.get("summary", "")

    # 显式提交：流式响应下依赖注入的 commit 时机不确定
    # （客户端中途断开时可能不提交），报告必须落库才能持久化展示。
    await db.commit()

    yield {
        "type": "done",
        "summary": report.get("summary", ""),
        "risk_count": len(report.get("risks", [])),
        "disclaimer": DISCLAIMER,
    }
