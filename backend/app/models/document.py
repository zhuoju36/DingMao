"""归档文件模型 - 合同、招标文件、签证单、往来文件、会议纪要等。"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project  # noqa: F401


class DocumentType(StrEnum):
    CONTRACT = "contract"              # 合同
    BIDDING = "bidding"                # 招标文件
    VARIATION = "variation"            # 签证单
    CORRESPONDENCE = "correspondence"  # 往来文件（工作联系单、会议纪要等）
    INSPECTION = "inspection"          # 监理通知单
    EVIDENCE = "evidence"              # 其他证据


class ProjectDocument(Base, TimestampMixin):
    __tablename__ = "project_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # 文件信息
    document_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # 存储信息（COS 路径或本地路径）
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(20), default="cos")

    # 解析结果（结构化提取的关键信息）
    parsed_content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending")
    parse_error: Mapped[str | None] = mapped_column(String(1000))

    # 文档相关日期
    document_date: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True))
    parties: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 涉及的相关方

    # 关系
    project: Mapped["Project"] = relationship(back_populates="documents")
