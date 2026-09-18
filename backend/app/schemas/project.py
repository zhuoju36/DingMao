"""项目相关 Pydantic schemas。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.user import UserRole


class ProjectCreate(BaseModel):
    """创建项目（合同审查场景下，W1 不上传文件，仅录入基础信息）。"""

    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    description: str | None = None
    location: str | None = Field(default=None, max_length=200)
    contract_amount: Decimal | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_duration_days: int | None = Field(default=None, ge=0)

    # 参建方
    owner_org: str | None = Field(default=None, max_length=200)
    design_org: str | None = Field(default=None, max_length=200)
    supervisor_org: str | None = Field(default=None, max_length=200)
    contractor_org: str | None = Field(default=None, max_length=200)

    # 用户在本项目的角色（必填，LLM 视角依据）
    role: UserRole

    # W1：合同关键条款用纯文本，结构化在 W2 上传文件时做
    contract_text: str | None = Field(
        default=None,
        description="W1: 合同关键条款/正文（纯文本，可选）",
    )


class ProjectResponse(BaseModel):
    id: int
    name: str
    code: str | None
    description: str | None
    location: str | None

    contract_amount: Decimal | None
    contract_start_date: date | None
    contract_end_date: date | None
    contract_duration_days: int | None

    owner_org: str | None
    design_org: str | None
    supervisor_org: str | None
    contractor_org: str | None

    # 用户在本项目的角色
    role: UserRole

    # W1 直接返回合同文本（不做结构化）
    contract_text: str | None = None

    contract_clauses: dict[str, Any] | None = None

    # P3-2 修复：Dashboard 排序需要此字段
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
