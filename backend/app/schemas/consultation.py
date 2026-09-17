"""问诊相关 Pydantic schemas。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.consultation import ConsultationScenario


class ConsultationCreate(BaseModel):
    """创建一次问诊会话。"""

    project_id: int
    scenario: ConsultationScenario = ConsultationScenario.CONTRACT_REVIEW


class SubmitTextRequest(BaseModel):
    """用户提交合同文本/事实（纯文本）。"""

    content: str = Field(min_length=1, description="用户输入的合同条款/事实描述")


class ConclusionResponse(BaseModel):
    id: int
    level: str  # red/yellow/green
    title: str
    content: str

    fact_refs: list[int]
    law_refs: list[dict[str, Any]]
    standard_refs: list[dict[str, Any]]

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
