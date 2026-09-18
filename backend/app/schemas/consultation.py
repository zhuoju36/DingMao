"""问诊相关 Pydantic schemas。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.consultation import ConsultationScenario

# ===== W3-W8 第 3 轮 EvidenceLinker 修复后（P2-2）：定义具体三源证据结构 =====

class LawRef(BaseModel):
    """法条引用（应用原则 3：version + effective_date 缺一不可）。

    这两个字段由 evidence_linker 从数据库直接取值填入，**不经 LLM**
    （应用原则 2）；缺失的引用在链接阶段就被丢弃，不会出现在这里。
    """

    code: str = Field(max_length=64)
    name: str | None = None  # 法律全称，展示用（如「中华人民共和国民法典」）
    article_no: str = Field(max_length=20)
    version: str
    effective_date: str = Field(max_length=10)  # YYYY-MM-DD


class StandardRef(BaseModel):
    """强条引用（同样由 evidence_linker 从库里取版本信息）。"""

    code: str = Field(max_length=64)
    name: str | None = None  # 标准全称，展示用
    clause_no: str = Field(max_length=20)
    version: str
    is_mandatory: bool
    effective_date: str | None = Field(default=None, max_length=10)


class ConsultationCreate(BaseModel):
    """创建一次问诊会话。"""

    project_id: int
    scenario: ConsultationScenario = ConsultationScenario.CONTRACT_REVIEW


class SubmitTextRequest(BaseModel):
    """用户提交合同文本/事实（纯文本）。"""

    content: str = Field(min_length=1, description="用户输入的合同条款/事实描述")


class ConclusionResponse(BaseModel):
    id: int
    level: Literal["red", "yellow", "green"]  # P2-1 修复：强类型保险
    title: str
    content: str

    fact_refs: list[int]
    law_refs: list[LawRef]               # P2-2 修复：替换 list[dict]
    standard_refs: list[StandardRef]     # P2-2 修复：替换 list[dict]

    reasoning_chain: str | None
    counter_arguments: str | None

    created_at: datetime

    model_config = {"from_attributes": True}


class FactResponse(BaseModel):
    id: int
    fact_key: str
    fact_label: str
    fact_value: str
    fact_value_type: str
    confidence: float

    created_at: datetime

    model_config = {"from_attributes": True}


# ===== 事实采集进度（consultation-ui.md 左栏「采集进度」面板的数据源）=====
#
# 前端**不硬编码**必填清单——登记表由后端下发，避免前后端各写一套而漂移
# （这正是此前状态机卡死的根因：必填键与实际写入键各写一套）。


class FactSpecOut(BaseModel):
    """单个事实键的规格（来自 constants.FACT_REGISTRY）。"""

    fact_key: str
    fact_label: str
    value_type: str
    required: bool
    question: str


class PendingFactOut(BaseModel):
    """未过置信度闸门、**未写库**的事实（等用户手动补）。"""

    fact_key: str
    fact_label: str
    reason: str


class FactProgressOut(BaseModel):
    """采集进度快照。"""

    required_total: int
    required_have: int
    missing_required: list[str] = []      # 缺失的必填 fact_key（有序）
    registry: list[FactSpecOut] = []      # 全量登记表，前端据此渲染清单
    pending: list[PendingFactOut] = []    # 待人工确认项（持久化在 state_data）


class ConsultationResponse(BaseModel):
    id: int
    project_id: int
    scenario: str
    status: str

    dispute_summary_user: str | None
    dispute_summary_ai: str | None

    current_step: str
    created_at: datetime
    updated_at: datetime

    facts: list[FactResponse] = []
    conclusions: list[ConclusionResponse] = []

    # 由 API 层填充（非 ORM 直接映射），见 _build_fact_progress()
    fact_progress: FactProgressOut | None = None
    # 三依据降级告警（落 consultations.state_data.evidence_warnings）
    # 见 consultation-ui.md §3.2a/b：缺版本号的引用被丢弃时必须可观测
    evidence_warnings: list[dict[str, Any]] = []

    model_config = {"from_attributes": True}


class GenerateReportResponse(BaseModel):
    """生成审查报告的响应。"""

    consultation_id: int
    status: str  # completed
    summary: str  # 一句话总结
    conclusions: list[ConclusionResponse]
    disclaimer: str  # 前置免责声明

    model_config = {"from_attributes": True}


class ConsultationMessageCreate(BaseModel):
    """用户发一条消息（多轮对话）。"""

    content: str = Field(min_length=1, max_length=2000)


class ConsultationMessageResponse(BaseModel):
    """问诊消息响应。"""

    id: int
    consultation_id: int
    role: str  # user / assistant / system
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatTurnResponse(BaseModel):
    """一轮对话响应（用户消息 + 助手消息 ID + 事实采集进度）。"""

    consultation_id: int
    user_message_id: int
    assistant_message_id: int
    assistant_content: str  # 完整内容（前端可二次展示）
    ready_to_report: bool  # 信息已充分建议生成报告
    fact_count: int

    # consultation-ui.md §6.1 缺口 7：这些字段由 service 层产出，
    # 但此前 response_model 没声明、端点也没构造，前端永远拿不到。
    current_step: str = "init"
    new_fact_labels: list[str] = []       # 本轮新写入的事实（人类标签）
    pending_facts: list[PendingFactOut] = []  # 未过闸门，需用户手动补
    fact_progress: FactProgressOut
    extraction_error: str | None = None   # 抽取失败时非空（前端需可见）


class ConfirmReportResponse(BaseModel):
    """确认生成报告的响应（状态机迁移 #6）。"""

    consultation_id: int
    current_step: str
    ready_to_report: bool
    missing_required: list[str] = []      # 仍缺的必填 fact_key（提前生成时非空）


class ConsultationDetailResponse(ConsultationResponse):
    """问诊详情（含 messages）。"""

    messages: list[ConsultationMessageResponse] = []


class ConsultationListItem(BaseModel):
    """项目下问诊列表项（不含 messages/conclusions 明细，用于列表展示）。"""

    id: int
    project_id: int
    project_name: str | None = None
    scenario: str
    status: str
    summary: str | None = None  # dispute_summary_ai
    fact_count: int = 0
    conclusion_count: int = 0
    red_count: int = 0
    yellow_count: int = 0
    green_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConsultationListResponse(BaseModel):
    project_id: int | None = None
    items: list[ConsultationListItem]
    total: int
