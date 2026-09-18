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


class DocumentListItem(BaseModel):
    """项目档案**列表项**（轻量，P0-7-C）。

    【为什么不复用 DocumentResponse】
    DocumentResponse 含 parsed_content.markdown（单份可达数十 KB）。
    列表若返回它，20 份文档的列表响应会膨胀到几百 KB —— 移动端/弱网明显卡。
    这里只暴露解析结果的**标量摘要**，markdown 由详情接口按需取。
    """

    id: int
    project_id: int
    uploader_id: int

    document_type: DocumentType
    title: str
    file_name: str
    file_size: int
    mime_type: str

    parse_status: ParseStatus
    parse_error: str | None

    # 从 parsed_content JSONB 提取的标量摘要（未解析时为 None/0）
    page_count: int = 0
    markdown_chars: int = 0
    parse_elapsed_sec: float | None = None

    # 源文件是否仍在存储中。
    # 用于把「DB 与存储不一致」这件事暴露到 UI，而不是等用户点「下载原文」才报错。
    # 触发场景：人工误删、存储迁移、磁盘故障。默认 True 以兼容老数据。
    file_available: bool = True

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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

    # 同 DocumentListItem.file_available
    file_available: bool = True

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
    """项目档案列表（含总数）。items 为轻量列表项，不含 markdown。"""

    items: list[DocumentListItem]
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
