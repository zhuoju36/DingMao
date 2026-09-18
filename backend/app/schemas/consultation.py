"""问诊相关 Pydantic schemas。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.consultation import ConsultationScenario


# ===== W3-W8 第 3 轮 EvidenceLinker 修复后（P2-2）：定义具体三源证据结构 =====

class LawRef(BaseModel):
    """法条引用（P0-2 修复：version 必填，对齐应用原则 3）。"""

    code: str = Field(max_length=64)
    article_no: str = Field(max_length=20)
    version: str  # 必填：EvidenceLinker 缺失时 raise EvidenceValidationError
    effective_date: str = Field(max_length=10)  # YYYY-MM-DD


class StandardRef(BaseModel):
    """强条引用。"""

    code: str = Field(max_length=64)
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
    """一轮对话响应（用户消息 + 助手消息 ID）。"""

    consultation_id: int
    user_message_id: int
    assistant_message_id: int
    assistant_content: str  # 完整内容（前端可二次展示）
    ready_to_report: bool  # 信息已充分建议生成报告
    fact_count: int


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
