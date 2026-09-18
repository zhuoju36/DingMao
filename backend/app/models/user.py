"""用户模型 - MVP 仅支持邮箱+密码注册。"""

from enum import StrEnum

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(StrEnum):
    """工程角色枚举。

    用户与项目都可携带 UserRole：
    - User.default_role：新建项目时的默认角色（表单预填）
    - Project.role：用户在该项目里的实际角色，LLM prompt 的视角依据
    """

    OWNER = "owner"              # 业主/建设单位
    DESIGNER = "designer"        # 设计单位
    SUPERVISOR = "supervisor"    # 监理单位
    CONTRACTOR = "contractor"    # 施工单位/总包
    SUBCONTRACTOR = "subcontractor"  # 其他分包商


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(100))
    # 角色已迁到项目级；此处保留为"新建项目时的默认角色"
    default_role: Mapped[str] = mapped_column(
        String(32), default=UserRole.SUPERVISOR.value, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
