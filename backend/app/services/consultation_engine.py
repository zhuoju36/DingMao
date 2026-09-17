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

from app.core.exceptions import ConsultationError
from app.models.consultation import (
    Consultation,
    ConsultationConclusion,
    ConsultationFact,
    ConsultationScenario,
    ConsultationStatus,
)
from app.models.user import User, UserRole
from app.services.llm import LLMMessage, LLMTaskType, get_llm_client
from app.services.llm_mock import generate_contract_review_report


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

    # 2. 调 mock LLM
    report = generate_contract_review_report(
        contract_text=contract_text,
        role=UserRole(user.role),
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


# ===== 流式输出 =====


def _build_report_prompt(
    role: UserRole,
    scenario: str,
    dispute_text: str,
) -> list[dict[str, str]]:
    """构造报告生成的 prompt messages（按场景分支）。"""
    # 不同场景用不同的 prompt 模板
    if scenario == "variation":
        # 变更扯皮场景
        system = (
            f"你是建工法律助手。角色视角：{role.value}。"
            "用户将描述一起工程变更/签证/索赔争议事实。"
            "请基于以下事实，结合建工行业惯例，识别法律风险点并给出处理建议。"
            "输出 JSON：{"
            '"risks": [{"clause": "事实要点", "level": "red|yellow|green", '
            '"reason": "风险分析 + 处理建议（建议具体可执行，如签证程序、证据保全等）"}], '
            '"summary": "一句话结论（包含核心风险定性）"}'
            "}"
        )
        user_msg = f"请分析以下变更争议事实：\n\n{dispute_text}"
    else:
        # 合同审查场景（默认）
        system = (
            f"你是建工法律助手。角色视角：{role.value}。"
            "分析合同条款，识别法律风险点。"
            "输出 JSON：{"
            '"risks": [{"clause": "条款摘要", "level": "red|yellow|green", '
            '"reason": "风险分析 + 修改建议（具体可执行）"}], '
            '"summary": "一句话结论（包含合同整体风险定性）"}'
            "}"
        )
        user_msg = f"分析以下合同条款：\n\n{dispute_text}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


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
    if contract_text is None:
        for fact in reversed(consultation.facts):
            if fact.fact_key == "contract_text":
                contract_text = fact.fact_value
                break

    if not contract_text:
        yield {"type": "error", "message": "未找到合同文本，请先调用 submit-text"}
        return

    client = get_llm_client()
    messages = _build_report_prompt(user, consultation.scenario, contract_text)

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

    await db.flush()

    yield {
        "type": "done",
        "summary": report.get("summary", ""),
        "risk_count": len(report.get("risks", [])),
    }
