"""项目档案 Pydantic schemas。

P0-7-A：上传 / 列表 / 详情
P0-7-B：解析状态机（pending → parsing → parsed / failed_parse）+ 重解析 + 删除
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models.document import DocumentType

# 解析状态枚举（P0-7-A：先有骨架，P0-7-B 填充真实解析结果）
ParseStatus = Literal[
    "pending",  # 已上传，待解析
    "parsing",  # 正在解析（P0-7-B）
    "parsed",  # 解析成功（P0-7-B）
    "failed_upload",  # 上传失败
    "failed_parse",  # 解析失败（P0-7-B）
    "archived",  # 已归档（V2）
]

StorageProvider = Literal["local", "cos"]  # P0-7-A 只用 local


class DocumentResponse(BaseModel):
    """项目档案响应（详情含 parsed_content）。"""

    id: int
    project_id: int
    uploader_id: int

    document_type: DocumentType
    title: str
    file_name: str
    file_size: int
    mime_type: str

    storage_path: str
    storage_provider: StorageProvider

    parse_status: ParseStatus
    parse_error: str | None

    # 解析产物（P0-7-B）。
    # 说明：只内联 markdown（供 LLM/检索）；middle.json / images/ 留盘，
    # 目录见 parsed_content["parsed_dir"]（相对 storage_root）。
    # 理由：middle.json 单文件可达数百 KB，内联进 JSONB 会明显膨胀 DB。
    parsed_content: dict[str, Any] | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReparseResponse(BaseModel):
    """重新解析响应。"""

    document_id: int
    parse_status: ParseStatus
    queued: bool  # False = 已在队列中，或任务队列不可用
    message: str


class DocumentListResponse(BaseModel):
    """项目档案列表（含分页总数）。"""

    items: list[DocumentResponse]
    total: int


class DocumentUploadResponse(BaseModel):
    """上传响应（与 DocumentResponse 相同，单独类型便于 API 文档）。"""

    id: int
    project_id: int
    document_type: DocumentType
    title: str
    file_name: str
    file_size: int
    mime_type: str
    storage_path: str
    storage_provider: StorageProvider
    parse_status: ParseStatus
    created_at: datetime

    model_config = {"from_attributes": True}
