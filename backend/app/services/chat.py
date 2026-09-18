"""多轮对话服务：上下文组装 + prompt 模板 + 知识库检索（W1 简化版）。

W1 知识库检索：直接用 SQL ILIKE（占位实现），W2 升级为 tsvector + 行为-强条映射。
"""

import re
from collections.abc import Iterable

from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consultation import ConsultationFact, ConsultationMessage
from app.models.knowledge import Law, LawArticle
from app.models.user import UserRole

# --- 场景标签 ---
_SCENARIO_LABELS = {
    "contract_review": "合同审查",
    "variation": "变更扯皮",
}

_ROLE_LABELS = {
    UserRole.OWNER: "业主/建设单位视角",
    UserRole.DESIGNER: "设计单位视角",
    UserRole.SUPERVISOR: "监理单位视角",
    UserRole.CONTRACTOR: "施工方视角",
    UserRole.SUBCONTRACTOR: "其他分包商视角",
}

# --- 提示收尾的判断 ---
def is_information_sufficient(
    fact_count: int, last_messages: list[ConsultationMessage]
) -> bool:
    """启发式：信息已充分（建议生成报告）。

    仅用于**合同审查**场景的旧简化链。变更扯皮场景走
    `consultation_state.is_facts_sufficient`（必填键 + 证据非空），
    不用这个"事实数 ≥4"的计数法。

    简单规则：
    - 已收集 ≥4 个事实
    - 或最近 3 条 assistant 消息都没有提出新问题（已满足询问）
    """
    if fact_count >= 4:
        return True
    recent_assistant = [m for m in last_messages[-3:] if m.role == "assistant"]
    return len(recent_assistant) >= 3  # 3 轮都没新问题 → 信息差不多够了


def build_chat_messages(
    role: UserRole,
    scenario: str,
    facts: list[ConsultationFact],
    knowledge_hits: list[dict[str, str]],
    recent_messages: list[ConsultationMessage],
    new_user_content: str,
) -> list[dict[str, str]]:
    """组装多轮对话的 LLM messages。"""
    role_label = _ROLE_LABELS.get(role, "工程方")
    scenario_label = _SCENARIO_LABELS.get(scenario, scenario)

    # 1. 已收集事实（按时间倒序，最近的更重要）
    facts_text = (
        "\n".join(f"- {f.fact_label}: {f.fact_value[:200]}" for f in facts)
        if facts
        else "（暂无）"
    )

    # 2. 知识库检索结果（最多 3 条）
    kb_text = (
        "\n".join(
            f"- 《{h['law_name']}》第{h['article_no']}条: {h['content'][:200]}"
            for h in knowledge_hits[:3]
        )
        if knowledge_hits
        else "（暂无相关法条）"
    )

    # 3. 角色化 system prompt
    system_prompt = (
        f"你是钉铆争议顾问。当前角色：{role_label}。\n"
        f"当前问诊类型：{scenario_label}。\n\n"
        f"**已收集的事实**（按时间排列）：\n{facts_text}\n\n"
        f"**相关法条知识库**（供参考）：\n{kb_text}\n\n"
        "你的任务：\n"
        "1. 基于已收集事实 + 知识库，给出有针对性的反馈\n"
        "2. **不重复**已知事实，只补充新视角或新问题\n"
        "3. 如果信息不足，主动问 1-2 个关键问题引导用户补充\n"
        "4. 如果信息已充分，明确告诉用户'信息已充分，建议生成报告'\n"
        "5. 回答简洁（≤200 字），用中文"
    )

    # 4. 历史消息（只取最近 10 轮，避免 context 爆炸）
    history: list[dict[str, str]] = []
    for m in recent_messages[-10:]:
        history.append({"role": m.role, "content": m.content})

    # 5. 当前用户消息
    history.append({"role": "user", "content": new_user_content})

    return [{"role": "system", "content": system_prompt}, *history]


# --- 知识库检索（W1 简化）---
_STOPWORDS = {"的", "了", "和", "是", "在", "我", "你", "他", "她", "它", "与"}


def extract_keywords(content: str) -> list[str]:
    """简单中文关键词抽取：长度≥3 且非停用词。"""
    words = re.findall(r"[\u4e00-\u9fff]{3,8}", content)
    return [w for w in words if w not in _STOPWORDS][:5]


async def search_laws(db: AsyncSession, content: str, limit: int = 3) -> list[dict[str, str]]:
    """在 laws + law_articles 里关键词检索。

    W1 实现：用 ILIKE + 数组包含。W2 升级 tsvector。
    """
    keywords = extract_keywords(content)
    if not keywords:
        return []

    hits: dict[str, dict[str, str]] = {}

    # 1. 检索 law_articles（正文/关键词命中）
    article_stmt = (
        select(LawArticle)
        .options(selectinload(LawArticle.law))
        .where(
            (cast(LawArticle.content, Text).ilike(f"%{keywords[0]}%"))
            | (cast(LawArticle.keywords, Text).ilike(f"%{keywords[0]}%"))
        )
        .limit(limit)
    )
    for a in (await db.execute(article_stmt)).scalars().all():
        key = f"{a.law.code}_{a.article_no}"
        if key not in hits:
            hits[key] = {
                "law_name": a.law.name,
                "law_code": a.law.code,
                "article_no": a.article_no,
                "content": a.content,
            }

    # 2. 补检索（如果 1 不够）
    if len(hits) < limit and len(keywords) > 1:
        law_stmt = (
            select(Law)
            .where(cast(Law.name, Text).ilike(f"%{keywords[1]}%"))
            .limit(limit - len(hits))
        )
        for law in (await db.execute(law_stmt)).scalars().all():
            # 补这个 law 的第一个 article
            article_stmt2 = (
                select(LawArticle)
                .options(selectinload(LawArticle.law))
                .where(LawArticle.law_id == law.id)
                .limit(1)
            )
            first = (await db.execute(article_stmt2)).scalar_one_or_none()
            if first:
                key = f"{law.code}_{first.article_no}"
                if key not in hits:
                    hits[key] = {
                        "law_name": law.name,
                        "law_code": law.code,
                        "article_no": first.article_no,
                        "content": first.content,
                    }

    return list(hits.values())[:limit]


def build_report_messages(
    role: UserRole,
    scenario: str,
    facts: list[ConsultationFact],
    evidence_block: str,
    all_messages: list[ConsultationMessage],
) -> list[dict[str, str]]:
    """组装"生成报告"的 LLM messages（合并所有上下文）。

    Args:
        evidence_block: 由 `evidence_linker.EvidenceCandidates.render_for_prompt()`
            渲染的候选条款清单。LLM **只能**从中挑标签，不得自己写条款号
            （应用原则 2）。此前的版本没有任何证据块，也没有要求 LLM 输出
            fact_refs/law_refs/standard_refs，导致落库的结论三依据恒为空。
    """
    role_label = _ROLE_LABELS.get(role, "工程方")
    scenario_label = _SCENARIO_LABELS.get(scenario, scenario)

    # 事实带 id 列出，LLM 才能用 fact_refs 指回来
    facts_text = (
        "\n".join(
            f"- [id={f.id}] {f.fact_label}: {f.fact_value[:300]}" for f in facts
        )
        if facts
        else "（无）"
    )

    if scenario == "variation":
        advice = "风险分析 + 处理建议（建议具体可执行）"
    else:
        advice = "风险分析 + 修改建议"

    system_prompt = (
        f"你是钉铆争议顾问。角色：{role_label}。问诊类型：{scenario_label}。\n\n"
        f"**已收集事实**（引用时只写 id 数字）：\n{facts_text}\n\n"
        f"**可用证据条款**：\n{evidence_block}\n\n"
        "**输出要求**：只输出 JSON，不要 markdown 围栏，不要任何解释文字。\n"
        "{\n"
        '  "risks": [\n'
        "    {\n"
        '      "title": "风险标题，不超过 20 字",\n'
        '      "level": "red | yellow | green",\n'
        f'      "content": "{advice}，200-500 字",\n'
        '      "fact_refs": [事实 id 数组，至少 1 个，只能填上面列出的 id],\n'
        '      "law_refs": ["L1", "L2"],\n'
        '      "standard_refs": ["S1"],\n'
        '      "reasoning_chain": "推理链，100-300 字",\n'
        '      "counter_arguments": "反例与例外，100-200 字"\n'
        "    }\n"
        "  ],\n"
        '  "summary": "一句话结论，不超过 100 字"\n'
        "}\n\n"
        "**等级判定**：\n"
        "- red：明确违法 / 合同无效 / 必须立即整改\n"
        "- yellow：风险较高 / 建议修改 / 有争议空间\n"
        "- green：风险可控 / 合规 / 可保留\n\n"
        "**铁律**（违反即视为生成失败）：\n"
        "1. 每条 risk 的 fact_refs 必须非空——结论必须挂在事实上（应用原则 1）\n"
        "2. law_refs / standard_refs **只能**填上面【可引用的…】清单里给出的标签。\n"
        "   绝对禁止自己编写法律名称、条款号、版本号或生效日期（应用原则 2）\n"
        "3. 上面没有可用条款时，law_refs / standard_refs 必须填 []，\n"
        "   并在 reasoning_chain 中明确写出「知识库中无明确对应依据」\n"
        "4. risks 数量 3-7 条；过多合并，过少补充\n"
        "5. counter_arguments 必须有内容，体现对反向可能的考虑"
    )

    # 历史对话作为 user/assistant 消息
    history: list[dict[str, str]] = []
    for m in all_messages[-20:]:
        history.append({"role": m.role, "content": m.content})

    return [{"role": "system", "content": system_prompt}, *history]



def split_messages_for_history(messages: Iterable[ConsultationMessage]) -> list[ConsultationMessage]:
    """返回按时间排序的消息列表（防御性排序）。"""
    return sorted(messages, key=lambda m: m.created_at)
