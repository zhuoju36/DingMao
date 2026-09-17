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

# --- 关键事实启发式（轻量关键词触发）---
_FACT_TRIGGERS = [
    (r"背靠背|背 靠 背|pay.{0,3}when.{0,3}paid", "背靠背付款条款"),
    (r"审计|审减|审定价|核减", "审计/审减条款"),
    (r"违约金.{0,8}(万分之|%|百分之|LPR|Lpr)", "违约金约定"),
    (r"保修期|质量保修|缺陷责任期", "保修期约定"),
    (r"工期.{0,8}(顺延|延误|延期|索赔)", "工期争议"),
    (r"签证|现场签证|工程签证", "现场签证"),
    (r"暂定价|暂估价|暂列金额", "暂定价/暂估价"),
    (r"业主.{0,4}(指令|指示|要求)", "业主指令"),
    (r"设计.{0,4}变更|设计变更|图纸.{0,4}变更", "设计变更"),
    (r"隐蔽.{0,4}工程|隐蔽.{0,4}验收", "隐蔽工程验收"),
]

# --- 提示收尾的判断 ---
def is_information_sufficient(fact_count: int, last_messages: list[ConsultationMessage]) -> bool:
    """启发式：信息已充分（建议生成报告）。

    简单规则：
    - 已收集 ≥4 个事实
    - 或最近 3 条 assistant 消息都没有提出新问题（已满足询问）
    """
    if fact_count >= 4:
        return True
    recent_assistant = [m for m in last_messages[-3:] if m.role == "assistant"]
    return len(recent_assistant) >= 3  # 3 轮都没新问题 → 信息差不多够了


def extract_fact_labels(content: str) -> list[str]:
    """从用户输入中抽取"已识别的事实类型"（用于状态显示）。

    返回触发的 fact_label 列表（去重）。
    """
    seen: set[str] = set()
    out: list[str] = []
    for pattern, label in _FACT_TRIGGERS:
        if re.search(pattern, content) and label not in seen:
            seen.add(label)
            out.append(label)
    return out


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
        f"你是钉铆法律助手。当前角色：{role_label}。\n"
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
    knowledge_hits: list[dict[str, str]],
    all_messages: list[ConsultationMessage],
) -> list[dict[str, str]]:
    """组装"生成报告"的 LLM messages（合并所有上下文）。"""
    role_label = _ROLE_LABELS.get(role, "工程方")
    scenario_label = _SCENARIO_LABELS.get(scenario, scenario)

    facts_text = (
        "\n".join(f"- {f.fact_label}: {f.fact_value[:300]}" for f in facts)
        if facts
        else "（无）"
    )

    kb_text = (
        "\n".join(
            f"- 《{h['law_name']}》第{h['article_no']}条: {h['content'][:200]}"
            for h in knowledge_hits[:5]
        )
        if knowledge_hits
        else "（无）"
    )

    # 场景化指令
    if scenario == "variation":
        output_schema = (
            "输出 JSON：{"
            '"risks": [{"clause": "事实要点", "level": "red|yellow|green", '
            '"reason": "风险分析 + 处理建议（建议具体可执行）"}], '
            '"summary": "一句话结论"}'
            "}"
        )
    else:
        output_schema = (
            "输出 JSON：{"
            '"risks": [{"clause": "条款摘要", "level": "red|yellow|green", '
            '"reason": "风险分析 + 修改建议"}], '
            '"summary": "一句话结论"}'
            "}"
        )

    system_prompt = (
        f"你是钉铆法律助手。角色：{role_label}。问诊类型：{scenario_label}。\n\n"
        f"**已收集事实**：\n{facts_text}\n\n"
        f"**相关法条知识库**：\n{kb_text}\n\n"
        f"基于以上事实 + 知识库 + 与用户的对话历史，生成完整审查/分析报告。{output_schema}"
    )

    # 历史对话作为 user/assistant 消息
    history: list[dict[str, str]] = []
    for m in all_messages[-20:]:
        history.append({"role": m.role, "content": m.content})

    return [{"role": "system", "content": system_prompt}, *history]


def extract_json_object(text: str) -> str | None:
    """从 LLM 输出中鲁棒提取第一个完整 JSON 对象。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0).strip() if match else None


def split_messages_for_history(messages: Iterable[ConsultationMessage]) -> list[ConsultationMessage]:
    """返回按时间排序的消息列表（防御性排序）。"""
    return sorted(messages, key=lambda m: m.created_at)
