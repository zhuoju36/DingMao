"""项目档案 Pydantic schemas。

P0-7-A（最小切片）：
- 上传文件（multipart）→ 存本地 → 写 DB（status=pending，不解析）
- 列表 / 详情查询

P0-7-B 后续（MinerU 异步解析）：parsed_content / parse_error 等字段填充。
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.document import DocumentType

# 解析状态枚举（P0-7-A：先有骨架，P0-7-B 填充真实解析结果）
ParseStatus = Literal[
    "pending",         # 已上传，待解析
    "parsing",         # 正在解析（P0-7-B）
    "parsed",          # 解析成功（P0-7-B）
    "failed_upload",   # 上传失败
    "failed_parse",    # 解析失败（P0-7-B）
    "archived",        # 已归档（V2）
]

StorageProvider = Literal["local", "cos"]  # P0-7-A 只用 local


class DocumentResponse(BaseModel):
    """项目档案响应。"""

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

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
