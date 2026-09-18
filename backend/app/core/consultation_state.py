"""问诊状态机（W3-W8 第 1 轮设计）。

6 节点状态机（变更扯皮场景）：
    init → collecting_facts → awaiting_confirm → generating_report
        → generating_artifacts → done

合同审查场景保留现有简化状态机（await_text → generating_report → done）。

详细迁移触发表见 docs/product/w3-w8-state-and-facts.md §2.2。
"""
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from app.core.constants import VARIATION_REQUIRED_FACT_KEYS

if TYPE_CHECKING:
    from app.models.consultation import ConsultationFact


class ConsultationStep(StrEnum):
    """6 节点状态机枚举。"""

    INIT = "init"
    COLLECTING_FACTS = "collecting_facts"
    AWAITING_CONFIRM = "awaiting_confirm"
    GENERATING_REPORT = "generating_report"
    GENERATING_ARTIFACTS = "generating_artifacts"
    DONE = "done"
    ABANDONED = "abandoned"


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
    (ConsultationStep.GENERATING_REPORT.value, ConsultationStep.GENERATING_ARTIFACTS.value),
    (ConsultationStep.GENERATING_ARTIFACTS.value, ConsultationStep.DONE.value),
})


# 异常路径：任意非 done 状态可转 abandoned
_ABANDON_FROM_ANY: frozenset[str] = frozenset({
    ConsultationStep.INIT.value,
    ConsultationStep.COLLECTING_FACTS.value,
    ConsultationStep.AWAITING_CONFIRM.value,
    ConsultationStep.GENERATING_REPORT.value,
    ConsultationStep.GENERATING_ARTIFACTS.value,
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
        必填事实键是否全部齐
    """
    if scenario == "variation":
        keys = {f.fact_key for f in facts}
        return VARIATION_REQUIRED_FACT_KEYS.issubset(keys)
    # contract_review: 复用现有 is_information_sufficient（chat.py）
    return False
