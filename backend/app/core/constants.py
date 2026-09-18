"""全局常量。

放跨模块共享的固定文本/配置，避免各处硬编码漂移。
"""

from dataclasses import dataclass
from enum import StrEnum

# 免责声明（AGENTS.md 应用原则 4：文书输出前必须显示前置免责声明）
#
# 使用位置：
# - app/services/llm_mock.py       生成报告时带出
# - app/services/consultation_engine.py  流式报告 done 事件带出
# - 前端 Consultation.vue          渲染在报告卡片顶部
DISCLAIMER = (
    "⚠️ 本报告由 AI 生成，仅供工程人员参考，不构成法律意见。"
    "重大决策前请由执业律师复核。"
)


# ===== 变更扯皮场景枚举（W3-W8 第 1 轮设计）=====


class DisputeType(StrEnum):
    """争议类型。"""

    PAYMENT = "payment"          # 付款争议
    QUALITY = "quality"          # 质量争议
    SCHEDULE = "schedule"        # 工期争议
    SCOPE = "scope"              # 工程范围争议
    OTHER = "other"


class DesiredOutcome(StrEnum):
    """期望结果。"""

    EXTEND_COMPENSATION = "extend_compensation"   # 延期 + 索赔
    EXTEND_SCHEDULE = "extend_schedule"           # 仅延期
    QUALITY_FIX = "quality_fix"                   # 整改
    OTHER = "other"


class EvidenceType(StrEnum):
    """证据类型（W3-W8 第 4 轮 P2-4 修复）。

    evidence_list JSON 字段中 type 的合法值。
    """

    CONTRACT_CLAUSE = "contract_clause"      # 合同条款
    CORRESPONDENCE = "correspondence"        # 沟通记录（监理通知单/工作联系单）
    VARIATION_ORDER = "variation_order"      # 签证单
    INSPECTION = "inspection"                # 现场检验记录
    PHOTO = "photo"                          # 现场照片
    CHAT_RECORD = "chat_record"              # 聊天记录截图
    OTHER = "other"


# ===== 变更扯皮事实键权威登记表 =====
#
# 单一事实来源（consultation-ui.md §6.3）：fact_key 的合法取值、人类标签、值类型、
# 是否必填、置信度闸门、缺失时的追问话术，**只在这里定义一次**。
# fact_extraction / is_facts_sufficient / 前端采集进度面板 全部从这里派生，
# 避免"必填键"和"实际写入的键"各写一套而漂移（这正是此前状态机卡死的根因）。
#
# 依据：docs/product/w3-w8-state-and-facts.md §3.1（9 键）
#      + w3-w8-artifacts.md §2.1 P1-8（第 10 键 duration_change_days）


class FactKey(StrEnum):
    """变更扯皮场景的事实键。"""

    DISPUTE_SUMMARY = "dispute_summary"
    DISPUTE_TYPE = "dispute_type"
    DISPUTE_DATE = "dispute_date"
    PARTIES_IN_DISPUTE = "parties_in_dispute"
    CONTRACT_CLAUSE_REF = "contract_clause_ref"
    EVIDENCE_LIST = "evidence_list"
    EVIDENCE_COMPLETE = "evidence_complete"
    CLAIMED_AMOUNT = "claimed_amount"
    DESIRED_OUTCOME = "desired_outcome"
    DURATION_CHANGE_DAYS = "duration_change_days"


# 置信度闸门（W3-W8 第 1 轮 P2-7 修复）
# 关键数字类 fact 的 confidence 低于此值时，service 层不写入 LLM 推断值
# （违反应用原则 2：LLM 不参与关键数字生成）
CRITICAL_NUMBER_CONFIDENCE_THRESHOLD = 0.7
CRITICAL_DATE_CONFIDENCE_THRESHOLD = 0.7
CRITICAL_CLAUSE_CONFIDENCE_THRESHOLD = 0.7

# 默认闸门（非关键类事实：AI 推断可接受，但低置信仍要在 UI 标记）
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class FactSpec:
    """单个事实键的完整规格。"""

    label: str
    value_type: str            # text / number / date / enum / json / bool
    required: bool
    confidence_gate: float     # < 此值时不采信 LLM 推断值
    question: str              # 缺失时的追问话术（chat_system 的关键询问清单）


FACT_REGISTRY: dict[str, FactSpec] = {
    FactKey.DISPUTE_SUMMARY: FactSpec(
        label="争议摘要", value_type="text", required=True,
        confidence_gate=0.5,
        question="请用一段话描述这次的争议。",
    ),
    FactKey.DISPUTE_TYPE: FactSpec(
        label="争议类型", value_type="enum", required=True,
        confidence_gate=DEFAULT_CONFIDENCE_THRESHOLD,
        question="这属于哪类争议？付款、质量、工期、工程范围，还是其他？",
    ),
    FactKey.DISPUTE_DATE: FactSpec(
        label="争议发生日期", value_type="date", required=True,
        confidence_gate=CRITICAL_DATE_CONFIDENCE_THRESHOLD,
        question="争议发生在哪一天？请给出具体日期。",
    ),
    FactKey.PARTIES_IN_DISPUTE: FactSpec(
        label="争议方", value_type="json", required=True,
        confidence_gate=DEFAULT_CONFIDENCE_THRESHOLD,
        question="涉及哪些主体？分别是业主、施工、监理还是设计单位？",
    ),
    FactKey.CONTRACT_CLAUSE_REF: FactSpec(
        label="合同依据条款", value_type="text", required=True,
        confidence_gate=CRITICAL_CLAUSE_CONFIDENCE_THRESHOLD,
        question="依据合同的哪一条？请给出条款号。",
    ),
    FactKey.EVIDENCE_LIST: FactSpec(
        label="证据清单", value_type="json", required=True,
        confidence_gate=0.5,
        question="您手头有哪些证据？现场照片、监理通知单、签证单、往来函件？",
    ),
    FactKey.EVIDENCE_COMPLETE: FactSpec(
        label="证据齐全确认", value_type="bool", required=False,
        confidence_gate=DEFAULT_CONFIDENCE_THRESHOLD,
        question="现有证据是否已经齐全？还有没有未提供的？",
    ),
    FactKey.CLAIMED_AMOUNT: FactSpec(
        label="索赔金额", value_type="number", required=False,
        confidence_gate=CRITICAL_NUMBER_CONFIDENCE_THRESHOLD,
        question="索赔金额是多少？请给出确定数字，不要用「约」「大概」。",
    ),
    FactKey.DESIRED_OUTCOME: FactSpec(
        label="期望结果", value_type="enum", required=False,
        confidence_gate=DEFAULT_CONFIDENCE_THRESHOLD,
        question="您期望的结果是？延期加索赔、仅延期、还是整改？",
    ),
    FactKey.DURATION_CHANGE_DAYS: FactSpec(
        label="工期增减天数", value_type="number", required=False,
        confidence_gate=CRITICAL_NUMBER_CONFIDENCE_THRESHOLD,
        question="工期需要顺延或缩减多少天？",
    ),
}


# 变更扯皮场景必填事实键（从登记表派生，禁止另行硬编码）
VARIATION_REQUIRED_FACT_KEYS: frozenset[str] = frozenset(
    k for k, spec in FACT_REGISTRY.items() if spec.required
)

# 稳定的展示顺序（前端左栏采集进度按此顺序渲染）
VARIATION_FACT_ORDER: tuple[str, ...] = tuple(FACT_REGISTRY)


def fact_label(fact_key: str) -> str:
    """取事实键的人类标签；未登记键原样返回（防 KeyError）。"""
    spec = FACT_REGISTRY.get(fact_key)
    return spec.label if spec else fact_key


def confidence_gate(fact_key: str) -> float:
    """取事实键的置信度闸门；未登记键用默认值。"""
    spec = FACT_REGISTRY.get(fact_key)
    return spec.confidence_gate if spec else DEFAULT_CONFIDENCE_THRESHOLD
