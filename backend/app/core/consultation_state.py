"""问诊状态机（W3-W8 第 1 轮设计）。

6 节点状态机（变更扯皮场景）：
    init → collecting_facts → awaiting_confirm → generating_report
        → generating_artifacts → done

合同审查场景保留现有简化状态机（await_text → generating_report → done）。

详细迁移触发表见 docs/product/w3-w8-state-and-facts.md §2.2。
"""
from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.core.constants import VARIATION_REQUIRED_FACT_KEYS, FactKey

if TYPE_CHECKING:
    from app.models.consultation import ConsultationFact


class ConsultationStep(StrEnum):
    """6 节点状态机枚举（+ 合同审查旧链 + failed 异常终态）。"""

    INIT = "init"
    COLLECTING_FACTS = "collecting_facts"
    AWAITING_CONFIRM = "awaiting_confirm"
    GENERATING_REPORT = "generating_report"
    GENERATING_ARTIFACTS = "generating_artifacts"
    DONE = "done"
    ABANDONED = "abandoned"
    # consultation-ui.md §3.2(c)：迁移表 #8/#10 引用了 failed，但枚举里原本没有，
    # 导致 LLM 生成失败后无处落脚、前端无法表达"重试生成"
    FAILED = "failed"
    # 合同审查场景的旧简化链首态（await_text → generating_report → done）。
    # 原实现把它硬编码给所有场景，variation 因此拿不到 init 初态、状态机卡死。
    AWAIT_TEXT = "await_text"


# 状态迁移合法性表（白名单，详见 §2.2 触发表）
# P0-5 修复：原设计 6 节点状态图只画了流转，迁移触发器完全缺失；
# 本表是落地时 chat_turn / generate_report 触发的依据
_ALLOWED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    # 正常流转
    (ConsultationStep.INIT.value, ConsultationStep.COLLECTING_FACTS.value),
    (ConsultationStep.COLLECTING_FACTS.value, ConsultationStep.COLLECTING_FACTS.value),
    (ConsultationStep.COLLECTING_FACTS.value, ConsultationStep.AWAITING_CONFIRM.value),
    (ConsultationStep.AWAITING_CONFIRM.value, ConsultationStep.COLLECTING_FACTS.value),
    (ConsultationStep.AWAITING_CONFIRM.value, ConsultationStep.GENERATING_REPORT.value),
    # collecting_facts 允许提前生成（consultation-ui.md §5.1：必填未齐只警告不阻断，
    # 选择权留给用户）。注意**不放开 init → generating_report**：
    # UI 上"生成报告"要求至少发过一条消息，init 到不了这一步，放开就是真的跳级。
    (ConsultationStep.COLLECTING_FACTS.value, ConsultationStep.GENERATING_REPORT.value),
    (ConsultationStep.GENERATING_REPORT.value, ConsultationStep.GENERATING_ARTIFACTS.value),
    (ConsultationStep.GENERATING_ARTIFACTS.value, ConsultationStep.DONE.value),
    # 异常路径（迁移表 #8/#10）：LLM 3 次 retry 仍失败
    (ConsultationStep.GENERATING_REPORT.value, ConsultationStep.FAILED.value),
    (ConsultationStep.GENERATING_ARTIFACTS.value, ConsultationStep.FAILED.value),
    # 失败后重试（consultation-ui.md §5.1：failed 态主按钮 = 重试生成）
    (ConsultationStep.FAILED.value, ConsultationStep.GENERATING_REPORT.value),
    # 合同审查场景的旧简化链（w3-w8-state-and-facts.md §1.1）
    (ConsultationStep.AWAIT_TEXT.value, ConsultationStep.GENERATING_REPORT.value),
    (ConsultationStep.AWAIT_TEXT.value, ConsultationStep.DONE.value),
})


# 异常路径：任意非 done 状态可转 abandoned
_ABANDON_FROM_ANY: frozenset[str] = frozenset({
    ConsultationStep.INIT.value,
    ConsultationStep.COLLECTING_FACTS.value,
    ConsultationStep.AWAITING_CONFIRM.value,
    ConsultationStep.GENERATING_REPORT.value,
    ConsultationStep.GENERATING_ARTIFACTS.value,
    ConsultationStep.FAILED.value,
    ConsultationStep.AWAIT_TEXT.value,
})


def can_transition(from_step: str, to_step: str) -> bool:
    """检查状态迁移是否合法。

    任意非 done 状态可转 abandoned（用户主动 / 30 天无活动）。
    """
    if to_step == ConsultationStep.ABANDONED.value:
        return from_step in _ABANDON_FROM_ANY
    return (from_step, to_step) in _ALLOWED_TRANSITIONS


def is_facts_sufficient(scenario: str, facts: list[ConsultationFact]) -> bool:
    """场景特定义"信息充分"判断（W3-W8 第 1 轮 §2.2）。

    Args:
        scenario: 问诊场景（"contract_review" / "variation"）
        facts: 该问诊已收集的事实列表

    Returns:
        必填事实键是否全部齐，且证据清单非空

    Note:
        §2.2 原文要求 variation 除必填键齐之外，**还要求 evidence_list 的 JSON 非空**
        （原实现漏了这半条）。空证据清单下宣称"信息充分"会直接违反应用原则 1。
    """
    if scenario == "variation":
        by_key = {f.fact_key: f for f in facts}
        if not VARIATION_REQUIRED_FACT_KEYS.issubset(by_key):
            return False
        evidence = by_key[FactKey.EVIDENCE_LIST]
        return bool(_parse_evidence(evidence.fact_value))
    # contract_review: 复用现有 is_information_sufficient（chat.py）
    return False


def _parse_evidence(raw: str | None) -> list[Any]:
    """把 evidence_list 的 fact_value 解析成列表；任何异常一律视为空。

    容错是刻意的：宁可判"信息不充分"让用户再补，也不因脏数据抛错中断问诊。
    """
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []
