"""问诊引擎：编排"合同审查"场景的核心流程。

W1 流程（合同审查场景）：
    1. 收集用户输入的合同文本
    2. 创建/获取 Consultation
    3. 调用 llm_mock 生成报告
    4. 存储事实 + 结论到数据库
    5. 返回 GenerateReportResponse
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    DISCLAIMER,
    FACT_REGISTRY,
    VARIATION_REQUIRED_FACT_KEYS,
)
from app.core.consultation_state import (
    ConsultationStep,
    can_transition,
    is_facts_sufficient,
)
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
from app.schemas.consultation import (
    ConsultationListItem,
    FactProgressOut,
    FactSpecOut,
    PendingFactOut,
)
from app.services.evidence_linker import (
    LAW_TERMS,
    STANDARD_TERMS,
    link_evidence,
    retrieve_candidates,
)
from app.services.fact_extraction import (
    ExtractedFact,
    ExtractionResult,
    extract_facts,
    missing_required_keys,
)
from app.services.llm import (
    LLMMessage,
    LLMTaskType,
    extract_json_object,
    get_llm_client,
)
from app.services.llm_mock import generate_contract_review_report

logger = logging.getLogger(__name__)

# 报告生成的最大尝试次数。原设计写"3 次 retry"（即最多 4 次调用），
# 单次约 20s，4 次会让用户等 80s。压到 2 次尝试（1 次重试）——
# json_mode 已禁用 thinking 且带 response_format，解析失败本就罕见。
_REPORT_MAX_ATTEMPTS = 2


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

    # 4. 更新状态（含状态机终态，旧实现只改 status 不改 current_step，
    #    导致合同审查问诊的 current_step 永远停在 await_text）
    if can_transition(
        consultation.current_step or "", ConsultationStep.DONE.value
    ) or consultation.current_step == ConsultationStep.AWAIT_TEXT.value:
        consultation.current_step = ConsultationStep.DONE.value
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
    """创建问诊会话。

    初始 step 按场景分流：
    - `variation` → `init`（W3-W8 六节点状态机，迁移 #1）
    - `contract_review` → `await_text`（旧简化链：await_text → generating_report → done）

    此前对**所有**场景硬编码 `await_text`，导致 variation 的初始态不是 `init`，
    `init → collecting_facts` 这条迁移永远不触发、状态机停在第一步
    （E2E 实测发现：事实全部抽到 6/6，但 step 始终是 await_text）。
    """
    initial_step = (
        ConsultationStep.INIT.value
        if scenario == ConsultationScenario.VARIATION
        else ConsultationStep.AWAIT_TEXT.value
    )
    consultation = Consultation(
        project_id=project_id,
        user_id=user_id,
        scenario=scenario.value,
        status=ConsultationStatus.IN_PROGRESS.value,
        current_step=initial_step,
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

    # 5. 结构化事实抽取（规范 fact_key）
    #
    # 这是事实的**唯一写入口**。此前写的是 chat_turn_{n} 假键，与
    # VARIATION_REQUIRED_FACT_KEYS 不相交，导致状态机卡死在 collecting_facts。
    #
    # 低置信度的关键数字/日期/条款号**不写库**（应用原则 2），记为 pending
    # 由前端提示用户手动补。
    extraction = ExtractionResult(accepted=[], pending=[], rejected=[])
    extraction_error: str | None = None
    if consultation_full.scenario == ConsultationScenario.VARIATION.value:
        try:
            extraction = await extract_facts(
                scenario=consultation_full.scenario,
                user_content=user_content,
                existing_keys={f.fact_key for f in consultation_full.facts},
            )
        except Exception as e:  # noqa: BLE001
            # 抽取失败不阻断对话（用户至少能看到 AI 回复），但必须可观测——
            # 应用原则 1 不允许事实静默丢失。
            extraction_error = f"{type(e).__name__}: {e}"
            logger.warning(
                "事实抽取失败 consultation=%s: %s", consultation.id, extraction_error
            )

    # 5a. 过闸门的事实 upsert：同键取置信度更高者，不覆盖用户更确定的陈述
    existing_by_key = {f.fact_key: f for f in consultation_full.facts}
    new_facts: list[ExtractedFact] = []
    for ef in extraction.accepted:
        prev = existing_by_key.get(ef.fact_key)
        if prev is not None:
            if prev.confidence >= ef.confidence:
                continue  # 已有更确定的版本，保留
            prev.fact_label = ef.fact_label
            prev.fact_value = ef.fact_value
            prev.fact_value_type = ef.fact_value_type
            prev.confidence = ef.confidence
            prev.source_message_id = user_msg.id
        else:
            db.add(
                ConsultationFact(
                    consultation_id=consultation.id,
                    fact_key=ef.fact_key,
                    fact_label=ef.fact_label,
                    fact_value=ef.fact_value,
                    fact_value_type=ef.fact_value_type,
                    source_type="user_input",
                    source_message_id=user_msg.id,
                    confidence=ef.confidence,
                )
            )
        new_facts.append(ef)
    await db.flush()

    # 5b. 以 DB 真实状态为准重新取事实（不要用内存拼装，避免漏掉历史轮次）
    facts_now = await load_facts(db, consultation.id)

    # 6. 信息充分性：直接由必填键集合判定，不再用「事实数 ≥4」的启发式计数
    all_messages = sorted(consultation_full.messages, key=lambda m: m.created_at)
    if consultation_full.scenario == ConsultationScenario.VARIATION.value:
        sufficient = is_facts_sufficient(consultation_full.scenario, facts_now)
    else:
        sufficient = is_information_sufficient(
            fact_count=len(facts_now),
            last_messages=all_messages + [user_msg, assistant_msg],
        )

    # 7. 状态机迁移（W3-W8 第 1 轮 §2.2 触发表）
    #    #2 init → collecting_facts        用户首次发言
    #    #3 collecting_facts → collecting_facts
    #    #4 collecting_facts → awaiting_confirm   必填齐 + 证据非空
    #    #5 awaiting_confirm → collecting_facts   用户又补了事实但仍不齐
    #
    # 落地取「由事实状态推导目标节点」的幂等方式，避免来回抖动；
    # 每次迁移都过 can_transition 白名单，不绕过状态机。
    current_step = consultation_full.current_step or ConsultationStep.INIT.value
    if current_step == ConsultationStep.INIT.value and can_transition(
        current_step, ConsultationStep.COLLECTING_FACTS.value
    ):
        consultation_full.current_step = ConsultationStep.COLLECTING_FACTS.value
        current_step = ConsultationStep.COLLECTING_FACTS.value

    target = (
        ConsultationStep.AWAITING_CONFIRM.value
        if sufficient
        else ConsultationStep.COLLECTING_FACTS.value
    )
    if current_step != target and can_transition(current_step, target):
        consultation_full.current_step = target
        current_step = target

    # ready_to_report 与状态机对齐：只有走到 awaiting_confirm 才提示可生成
    ready = current_step == ConsultationStep.AWAITING_CONFIRM.value

    # 待人工确认项持久化到 state_data：刷新页面后仍要能看到「⚠️ 索赔金额待确认」
    state = dict(consultation_full.state_data or {})
    state["pending_facts"] = [
        {"fact_key": f.fact_key, "fact_label": f.fact_label, "reason": f.reason}
        for f in extraction.pending
    ]
    if extraction_error:
        state["last_extraction_error"] = extraction_error
    else:
        state.pop("last_extraction_error", None)
    consultation_full.state_data = state

    return {
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
        "assistant_content": full_content,
        "ready_to_report": ready,
        "fact_count": len(facts_now),
        "new_fact_labels": [f.fact_label for f in new_facts],
        "current_step": consultation_full.current_step,
        "pending_facts": [
            {"fact_key": f.fact_key, "fact_label": f.fact_label, "reason": f.reason}
            for f in extraction.pending
        ],
        "fact_progress": build_fact_progress(facts_now, extraction.pending),
        "extraction_error": extraction_error,
    }


_EXPAND_SYSTEM = """你是工程法律检索助手。任务：从给定词表中**挑选**与案情相关的检索词。

铁律：
1. 只能从下面给出的词表里挑词，**绝对不许自己造词**。
   原因：这些词是经过验证的、确定能在法条/强条原文里查到的；
   你自造的词（如「工程变更」）在原文里并不存在，会导致检索落空。
2. 挑选标准：该词是这起争议在法律上的**核心概念**，而不是案情的复述。
3. 挑 8-14 个词，覆盖：争议主体、争议标的、法律行为、法律后果。
4. 只输出 JSON：{"terms": ["词1", "词2", ...]}
"""


async def expand_search_terms(
    *, facts: list[ConsultationFact], user_content: str
) -> list[str]:
    """用 LLM 从**受控词表**里挑选法律检索词（查询扩展）。

    为什么需要：案情是口语（"索赔""工期顺延"），法条是法言法语
    （"赔偿损失""顺延工程日期"），子串匹配对不上。实测主场景
    （幕墙变更 + 索赔 + 工期顺延）仅靠案情自身用词召回 **0 条**候选；
    加上扩展词后 6 条，且命中《民法典》第806条（转包/解除）等正确条款。

    为什么必须是"选"而不是"写"：让 LLM 自由生成检索词会产出「工程变更」
    这类词——而法条原文写的是「工程范围」「变更」，子串匹配必然落空。
    受控词表保证产出的词一定能查到。

    Returns:
        受控词表内的扩展词；失败返回空列表（检索退化为仅用案情自身用词，
        不阻断报告生成）。
    """
    case_parts = [f"{f.fact_label}：{f.fact_value}" for f in facts]
    case_parts.append(f"用户描述：{user_content}")
    case_text = "\n".join(case_parts)[:2500]

    prompt = (
        "【可选词表 — 法条检索词】\n"
        + "、".join(LAW_TERMS)
        + "\n\n【可选词表 — 强条检索词】\n"
        + "、".join(STANDARD_TERMS)
        + f"\n\n【案情】\n{case_text}\n\n只输出 JSON："
    )

    client = get_llm_client()
    try:
        payload = await client.complete_json(
            LLMTaskType.CLAUSE_EXTRACTION,
            [
                LLMMessage("system", _EXPAND_SYSTEM),
                LLMMessage("user", prompt),
            ],
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("检索词扩展失败，退化为仅用案情用词: %s", e)
        return []

    raw = payload.get("terms")
    if not isinstance(raw, list):
        return []

    allowed = set(LAW_TERMS) | set(STANDARD_TERMS)
    picked: list[str] = []
    dropped: list[str] = []
    for t in raw:
        word = str(t).strip()
        if not word:
            continue
        if word in allowed:
            if word not in picked:
                picked.append(word)
        else:
            dropped.append(word)

    if dropped:
        logger.info("检索词扩展：丢弃 %d 个不在受控词表内的词 %s", len(dropped), dropped)
    logger.info("检索词扩展：采用 %d 个 %s", len(picked), picked)
    return picked


async def load_facts(
    db: AsyncSession, consultation_id: int
) -> list[ConsultationFact]:
    """加载某问诊的全部事实（按创建时间稳定排序）。"""
    result = await db.execute(
        select(ConsultationFact)
        .where(ConsultationFact.consultation_id == consultation_id)
        .order_by(ConsultationFact.created_at, ConsultationFact.id)
    )
    return list(result.scalars().all())


def build_fact_progress(
    facts: list[ConsultationFact],
    pending: list[ExtractedFact] | None = None,
) -> FactProgressOut:
    """构造采集进度快照（左栏「采集进度」面板的数据源）。

    登记表（registry）随响应下发，前端不硬编码——单一事实来源在
    `constants.FACT_REGISTRY`，避免前后端清单漂移（这正是此前状态机卡死的根因：
    必填键与实际写入键各写一套）。
    """
    present = {f.fact_key for f in facts}
    missing = missing_required_keys(present)
    required_total = len(VARIATION_REQUIRED_FACT_KEYS)
    return FactProgressOut(
        required_total=required_total,
        required_have=required_total - len(missing),
        missing_required=missing,
        registry=[
            FactSpecOut(
                fact_key=key,
                fact_label=spec.label,
                value_type=spec.value_type,
                required=spec.required,
                question=spec.question,
            )
            for key, spec in FACT_REGISTRY.items()
        ],
        pending=[
            PendingFactOut(
                fact_key=f.fact_key, fact_label=f.fact_label, reason=f.reason
            )
            for f in (pending or [])
        ],
    )


def pending_from_state(state_data: dict[str, Any] | None) -> list[ExtractedFact]:
    """从 state_data 还原待确认项（刷新页面后仍能展示）。"""
    raw = (state_data or {}).get("pending_facts") or []
    if not isinstance(raw, list):
        return []
    out: list[ExtractedFact] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            ExtractedFact(
                fact_key=str(item.get("fact_key", "")),
                fact_label=str(item.get("fact_label", "")),
                fact_value="",
                fact_value_type="",
                confidence=0.0,
                reason=str(item.get("reason", "")),
            )
        )
    return out


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

    from app.services.chat import build_report_messages

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

    # 三依据检索（检索优先：先把候选条款编号注入 prompt，LLM 只挑标签。
    # 见 app/services/evidence_linker.py 模块文档与决策日志 §2026-09）
    # 查询扩展：把案情口语映射到法条词汇（否则子串匹配召回接近 0）
    extra_terms = await expand_search_terms(
        facts=list(consultation_full.facts),
        user_content=search_text,
    )
    candidates = await retrieve_candidates(db, search_text, extra_terms=extra_terms)
    evidence_block = candidates.render_for_prompt()

    fact_by_id = {f.id: f for f in consultation_full.facts}
    valid_fact_ids = set(fact_by_id)

    messages = build_report_messages(
        role=user,
        scenario=consultation.scenario,
        facts=list(consultation_full.facts),
        evidence_block=evidence_block,
        all_messages=list(consultation_full.messages),
    )

    # 流式生成 + 解析。JSON 不合法时重试一次（把错误塞回去让模型自修）；
    # 仍失败则置 failed，**不**自动转 done（w3-w8-llm-prompts.md §5.2）。
    report: dict[str, Any] | None = None
    parse_error: str = ""
    for attempt in range(_REPORT_MAX_ATTEMPTS):
        if attempt > 0:
            # 已经有半截内容流给前端了，先让它清空预览再重试
            yield {"type": "reset"}
            messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        f"上一次输出无法解析为 JSON（{parse_error}）。"
                        "请重新只输出合法 JSON，不要任何解释或 markdown 围栏。"
                    ),
                },
            ]

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
            parse_error = f"LLM 调用失败: {e}"
            logger.warning("报告生成第 %d 次调用失败: %s", attempt + 1, e)
            continue

        full_content = "".join(chunks)
        # 先剥 <think>/代码围栏再抽 JSON（M3 两种模式各有各的脏）
        json_text = extract_json_object(full_content)
        if not json_text:
            parse_error = "模型未输出 JSON 对象"
            continue
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            parse_error = f"JSON 解析失败: {e}"
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("risks"), list):
            parse_error = "JSON 缺少 risks 数组"
            continue
        report = parsed
        break

    if report is None:
        # 兜底：保留用户所有事实，置 failed，写入一条 system 消息
        consultation.status = ConsultationStatus.FAILED.value
        consultation.current_step = ConsultationStep.FAILED.value
        db.add(
            ConsultationMessage(
                consultation_id=consultation.id,
                role="system",
                content=(
                    "⚠️ 因网络/服务问题暂无法生成完整报告，已保留您提供的所有事实。"
                    "建议稍后重试。"
                ),
            )
        )
        await db.commit()
        yield {
            "type": "error",
            "message": f"报告生成失败（已重试 {_REPORT_MAX_ATTEMPTS} 次）：{parse_error}",
        }
        return

    # 写结论到 DB（含三依据）
    warnings: list[dict[str, Any]] = []
    for idx, c in enumerate(report.get("risks", [])):
        if not isinstance(c, dict):
            continue

        level = str(c.get("level", "yellow")).lower()
        if level not in ("red", "yellow", "green"):
            warnings.append(
                {
                    "scope": "conclusion",
                    "index": idx,
                    "type": "invalid_level",
                    "detail": f"等级取值非法 {level!r}，已按 yellow 处理",
                }
            )
            level = "yellow"

        # --- 🟦 事实引用：必须是本 consultation 的 fact id ---
        raw_refs = c.get("fact_refs")
        raw_refs = raw_refs if isinstance(raw_refs, list) else []
        fact_refs = [
            int(i) for i in raw_refs if isinstance(i, int) and i in valid_fact_ids
        ]
        bad_refs = [i for i in raw_refs if not (isinstance(i, int) and i in valid_fact_ids)]
        if bad_refs:
            warnings.append(
                {
                    "scope": "ref",
                    "index": idx,
                    "type": "invalid_fact_id",
                    "detail": f"丢弃无效事实引用：{bad_refs}",
                }
            )

        # --- 🟨 法条 / 🟥 强条：标签 → 真实 DB 行 ---
        link = link_evidence(
            law_labels=_as_str_list(c.get("law_refs")),
            standard_labels=_as_str_list(c.get("standard_refs")),
            candidates=candidates,
            conclusion_index=idx,
        )
        warnings.extend(link.warnings)

        if not fact_refs:
            warnings.append(
                {
                    "scope": "conclusion",
                    "index": idx,
                    "type": "no_fact_basis",
                    "detail": "该结论未挂任何事实依据，按应用原则 1 不升格",
                }
            )

        # 应用原则 1「无依据不升格结论」：三依据全空的断言降到最低等级。
        # 只缺 🟦 但有 🟨/🟥 时保留原等级——不静默下调真实红线。
        if not fact_refs and not link.law_refs and not link.standard_refs:
            warnings.append(
                {
                    "scope": "conclusion",
                    "index": idx,
                    "type": "unsupported_conclusion",
                    "detail": f"结论「{c.get('title') or c.get('clause')}」三依据全空，"
                    f"等级由 {level} 降为 green",
                }
            )
            level = "green"

        db.add(
            ConsultationConclusion(
                consultation_id=consultation.id,
                level=level,
                # 兼容旧字段名 clause/reason，模型偶尔会沿用
                title=str(c.get("title") or c.get("clause") or "未命名风险")[:300],
                content=str(c.get("content") or c.get("reason") or ""),
                fact_refs=fact_refs,
                law_refs=link.law_refs,
                standard_refs=link.standard_refs,
                reasoning_chain=_opt_str(c.get("reasoning_chain")),
                counter_arguments=_opt_str(c.get("counter_arguments")),
            )
        )

    consultation.status = ConsultationStatus.COMPLETED.value
    consultation.current_step = ConsultationStep.DONE.value
    consultation.dispute_summary_ai = report.get("summary", "")

    # 降级 warning 落 state_data（不新增列，见 consultation-ui.md §3.2b）。
    # JSONB 用整体重新赋值，否则 SQLAlchemy 检测不到变更。
    state = dict(consultation.state_data or {})
    state["evidence_warnings"] = warnings
    state["evidence_candidates"] = {
        "laws": len(candidates.laws),
        "laws_citable": sum(1 for c in candidates.laws if c.citable),
        "standards": len(candidates.standards),
        "standards_citable": sum(1 for c in candidates.standards if c.citable),
        "terms": candidates.terms_used,
    }
    consultation.state_data = state

    # 显式提交：流式响应下依赖注入的 commit 时机不确定
    # （客户端中途断开时可能不提交），报告必须落库才能持久化展示。
    await db.commit()

    yield {
        "type": "done",
        "summary": report.get("summary", ""),
        "risk_count": len(report.get("risks", [])),
        "disclaimer": DISCLAIMER,
        "warnings": warnings,
    }


def _as_str_list(value: Any) -> list[str]:
    """把 LLM 给的标签字段规整成字符串列表（容忍 None / 字符串 / 混合数组）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _opt_str(value: Any) -> str | None:
    """可选字符串字段。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
