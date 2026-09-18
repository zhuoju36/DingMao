"""项目档案模型 - 单用户单项目，跨场景复用。"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import UserRole

if TYPE_CHECKING:
    from app.models.consultation import Consultation  # noqa: F401
    from app.models.document import ProjectDocument  # noqa: F401


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # 基础信息
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), index=True)  # 工程编号
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))

    # 合同关键信息
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    contract_start_date: Mapped[date | None] = mapped_column(Date)
    contract_end_date: Mapped[date | None] = mapped_column(Date)
    contract_duration_days: Mapped[int | None] = mapped_column()

    # 参建方
    owner_org: Mapped[str | None] = mapped_column(String(200))
    design_org: Mapped[str | None] = mapped_column(String(200))
    supervisor_org: Mapped[str | None] = mapped_column(String(200))
    contractor_org: Mapped[str | None] = mapped_column(String(200))

    # 用户在本项目的角色（LLM prompt 视角依据；项目级而非用户级）
    role: Mapped[str] = mapped_column(
        String(32), default=UserRole.SUPERVISOR.value, nullable=False
    )

    # 合同关键条款（JSONB 存储解析后的结构化条款）
    contract_clauses: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # 关系 - 用 string forward ref 避免循环 import
    documents: Mapped[list["ProjectDocument"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    consultations: Mapped[list["Consultation"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
