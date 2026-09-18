"""W3-W8 第 1 切片测试：基础骨架（常量 + 状态机 + 序列化）。

独立单测，不依赖数据库 / LLM。
"""
from datetime import date

from app.core.constants import (
    DesiredOutcome,
    DisputeType,
    EvidenceType,
    VARIATION_REQUIRED_FACT_KEYS,
)
from app.core.consultation_state import (
    ConsultationStep,
    can_transition,
    is_facts_sufficient,
)
from app.services.fact_serializer import (
    deserialize_fact_value,
    serialize_fact_value,
)


# ===== constants.py 枚举测试 =====

def test_dispute_type_values():
    assert DisputeType.PAYMENT.value == "payment"
    assert DisputeType.QUALITY.value == "quality"
    assert DisputeType.SCHEDULE.value == "schedule"
    assert DisputeType.SCOPE.value == "scope"
    assert DisputeType.OTHER.value == "other"


def test_desired_outcome_values():
    assert DesiredOutcome.EXTEND_COMPENSATION.value == "extend_compensation"
    assert DesiredOutcome.EXTEND_SCHEDULE.value == "extend_schedule"
    assert DesiredOutcome.QUALITY_FIX.value == "quality_fix"


def test_evidence_type_values():
    """P2-4 修复：枚举值与第 1 轮 fact schema 一致。"""
    assert EvidenceType.CONTRACT_CLAUSE.value == "contract_clause"
    assert EvidenceType.CORRESPONDENCE.value == "correspondence"
    assert EvidenceType.VARIATION_ORDER.value == "variation_order"
    assert EvidenceType.INSPECTION.value == "inspection"
    assert EvidenceType.PHOTO.value == "photo"
    assert EvidenceType.CHAT_RECORD.value == "chat_record"
    assert EvidenceType.OTHER.value == "other"


def test_variation_required_fact_keys():
    """第 1 轮 §3.1：6 个必填事实键。"""
    assert VARIATION_REQUIRED_FACT_KEYS == frozenset({
        "dispute_summary",
        "dispute_type",
        "dispute_date",
        "parties_in_dispute",
        "evidence_list",
        "contract_clause_ref",
    })


# ===== consultation_state.py 状态机测试 =====

def test_consultation_step_enum():
    assert ConsultationStep.INIT.value == "init"
    assert ConsultationStep.COLLECTING_FACTS.value == "collecting_facts"
    assert ConsultationStep.AWAITING_CONFIRM.value == "awaiting_confirm"
    assert ConsultationStep.GENERATING_REPORT.value == "generating_report"
    assert ConsultationStep.GENERATING_ARTIFACTS.value == "generating_artifacts"
    assert ConsultationStep.DONE.value == "done"
    assert ConsultationStep.ABANDONED.value == "abandoned"


def test_can_transition_normal_flow():
    """P0-5 修复：6 节点状态机迁移白名单生效。"""
    # 正常流转
    assert can_transition("init", "collecting_facts") is True
    assert can_transition("collecting_facts", "collecting_facts") is True
    assert can_transition("collecting_facts", "awaiting_confirm") is True
    assert can_transition("awaiting_confirm", "collecting_facts") is True  # 补充事实
    assert can_transition("awaiting_confirm", "generating_report") is True
    assert can_transition("generating_report", "generating_artifacts") is True
    assert can_transition("generating_artifacts", "done") is True


def test_can_transition_illegal_skip():
    """状态机不允许跳级（如 init 直接跳 generating_report）。"""
    assert can_transition("init", "generating_report") is False
    assert can_transition("init", "done") is False
    assert can_transition("collecting_facts", "done") is False


def test_can_transition_done_is_terminal():
    """done 状态不能再迁移（除非是 abandoned，但 done 不在 abandon 白名单）。"""
    assert can_transition("done", "collecting_facts") is False
    assert can_transition("done", "generating_artifacts") is False


def test_can_transition_abandon_any_non_done():
    """任意非 done 状态可转 abandoned（异常路径）。"""
    for step in ["init", "collecting_facts", "awaiting_confirm", "generating_report", "generating_artifacts"]:
        assert can_transition(step, "abandoned") is True, f"{step} → abandoned 应允许"
    # done 不能直接 abandoned（语义上已完成）
    assert can_transition("done", "abandoned") is False


def test_is_facts_sufficient_variation():
    """第 1 轮 §2.2：变更扯皮场景必填 6 键全齐**且证据清单非空**才算充分。"""

    class FakeFact:
        def __init__(self, fact_key: str, fact_value: str = "x"):
            self.fact_key = fact_key
            self.fact_value = fact_value

    def build(**overrides: str) -> list[FakeFact]:
        """构造必填键全齐的事实列表；overrides 可覆盖某个键的值。"""
        return [
            FakeFact(k, overrides.get(k, '[{"type":"photo","ref":"p1"}]' if k == "evidence_list" else "x"))
            for k in VARIATION_REQUIRED_FACT_KEYS
        ]

    # 全部齐 + 证据非空
    assert is_facts_sufficient("variation", build()) is True

    # 缺一个键
    facts = [f for f in build() if f.fact_key != "dispute_date"]
    assert is_facts_sufficient("variation", facts) is False

    # 完全空
    assert is_facts_sufficient("variation", []) is False

    # 键齐但证据清单为空列表 → 不充分（§2.2 的"且 evidence_list 非空"，原实现漏了）
    assert is_facts_sufficient("variation", build(evidence_list="[]")) is False

    # 证据清单脏数据 → 判不充分，且不抛错
    assert is_facts_sufficient("variation", build(evidence_list="{ 坏 JSON")) is False
    assert is_facts_sufficient("variation", build(evidence_list="")) is False


def test_is_facts_sufficient_contract_review_legacy():
    """合同审查场景：暂返回 False，由 chat_turn 现有 is_information_sufficient 处理。"""
    assert is_facts_sufficient("contract_review", []) is False


# ===== fact_serializer.py 测试 =====

def test_serialize_text():
    assert serialize_fact_value("hello", "text") == "hello"
    assert serialize_fact_value("中文测试", "text") == "中文测试"


def test_serialize_number():
    assert serialize_fact_value(280000, "number") == "280000"
    assert serialize_fact_value(280000.5, "number") == "280000.5"


def test_serialize_bool():
    assert serialize_fact_value(True, "bool") == "True"
    assert serialize_fact_value(False, "bool") == "False"


def test_serialize_date_datetime():
    """P2-6 修复：date / datetime 统一转 YYYY-MM-DD。"""
    assert serialize_fact_value(date(2026, 4, 15), "date") == "2026-04-15"
    from datetime import datetime
    assert serialize_fact_value(datetime(2026, 4, 15, 10, 30), "date") == "2026-04-15"


def test_serialize_json_compact():
    """P2-6 修复：json 类型紧凑格式（无空格），便于检索。"""
    parties = [{"role": "owner", "name": "Acme"}, {"role": "contractor", "name": "Builder"}]
    s = serialize_fact_value(parties, "json")
    assert s == '[{"role":"owner","name":"Acme"},{"role":"contractor","name":"Builder"}]'
    # 紧凑：, 和 : 后无空格（但 content 字符串内可有空格）
    assert ',"' in s  # 紧凑分隔
    assert '": "' not in s  # key: value 间无空格


def test_serialize_json_unicode():
    """中文 JSON 不被 escape。"""
    parties = [{"role": "施工方", "name": "YY 建设集团"}]
    s = serialize_fact_value(parties, "json")
    assert "施工方" in s
    assert "\\u" not in s  # ensure_ascii=False


def test_deserialize_round_trip():
    """序列化 → 反序列化 数据一致。"""
    test_cases = [
        ("hello", "text"),
        (280000, "number"),
        (True, "bool"),
        (date(2026, 4, 15), "date"),
        ([{"role": "owner", "name": "XX"}], "json"),
    ]
    for value, t in test_cases:
        raw = serialize_fact_value(value, t)
        restored = deserialize_fact_value(raw, t)
        if t == "date":
            assert restored == "2026-04-15"  # date 转字符串后，restore 是字符串
        elif t == "json":
            assert restored == value
        else:
            assert restored == value


def test_deserialize_empty():
    """空字符串反序列化返回 None（不抛错）。"""
    assert deserialize_fact_value("", "text") is None
    assert deserialize_fact_value("", "json") is None
    assert deserialize_fact_value("", "number") is None
