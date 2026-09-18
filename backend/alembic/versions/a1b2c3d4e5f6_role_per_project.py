"""role per project: users.role -> users.default_role + projects.role

Revision ID: a1b2c3d4e5f6
Revises: 52779635ca3f
Create Date: 2026-09-18 12:00:00.000000

角色机制反转（详见 docs/product/decision-log.md 同日条目）：
- users.role 重命名为 users.default_role（新建项目表单预填）
- projects 新增 role 列（NOT NULL，LLM 视角依据）
- 用 users.default_role 回填现有 projects.role
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "52779635ca3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. users.role -> users.default_role
    op.alter_column(
        "users",
        "role",
        new_column_name="default_role",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )

    # 2. projects.role 新增（先给 server_default 让历史行不阻塞 NOT NULL）
    op.add_column(
        "projects",
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="supervisor",
        ),
    )

    # 3. 用 owner 的 default_role 回填现有 projects.role
    #    （覆盖式 UPDATE：已存在的 server_default 会被真正的 user role 替换）
    op.execute(
        """
        UPDATE projects AS p
        SET role = u.default_role
        FROM users AS u
        WHERE p.owner_id = u.id
          AND p.role <> u.default_role
        """
    )


def downgrade() -> None:
    # 1. projects.role 先反填回 user.default_role（把每个用户最近的 project role 回写）
    op.execute(
        """
        UPDATE users AS u
        SET default_role = COALESCE(
            (SELECT p.role FROM projects AS p
             WHERE p.owner_id = u.id
             ORDER BY p.created_at DESC
             LIMIT 1),
            u.default_role
        )
        """
    )

    # 2. 删 projects.role
    op.drop_column("projects", "role")

    # 3. users.default_role -> users.role
    op.alter_column(
        "users",
        "default_role",
        new_column_name="role",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )