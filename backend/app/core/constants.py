"""全局常量。

放跨模块共享的固定文本/配置，避免各处硬编码漂移。
"""

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

from enum import Enum


class DisputeType(str, Enum):
    """争议类型。"""

    PAYMENT = "payment"          # 付款争议
    QUALITY = "quality"          # 质量争议
    SCHEDULE = "schedule"        # 工期争议
    SCOPE = "scope"              # 工程范围争议
    OTHER = "other"


class DesiredOutcome(str, Enum):
    """期望结果。"""

    EXTEND_COMPENSATION = "extend_compensation"   # 延期 + 索赔
    EXTEND_SCHEDULE = "extend_schedule"           # 仅延期
    QUALITY_FIX = "quality_fix"                   # 整改
    OTHER = "other"


class EvidenceType(str, Enum):
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


# 变更扯皮场景必填事实键（W3-W8 第 1 轮 §三）
VARIATION_REQUIRED_FACT_KEYS: frozenset[str] = frozenset({
    "dispute_summary",
    "dispute_type",
    "dispute_date",
    "parties_in_dispute",
    "evidence_list",
    "contract_clause_ref",
})


# 置信度闸门（W3-W8 第 1 轮 P2-7 修复）
# 关键数字类 fact 的 confidence 低于此值时，service 层不写入 LLM 推断值
# （违反应用原则 2：LLM 不参与关键数字生成）
CRITICAL_NUMBER_CONFIDENCE_THRESHOLD = 0.7
CRITICAL_DATE_CONFIDENCE_THRESHOLD = 0.7
CRITICAL_CLAUSE_CONFIDENCE_THRESHOLD = 0.7
