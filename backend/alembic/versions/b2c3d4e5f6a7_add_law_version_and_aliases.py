"""add law version and aliases

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18 12:30:00.000000

W3-W8 第 3 轮 P0-1 / P0-3 修复（详见 docs/product/w3-w8-triple-evidence.md §3.1）：

1. 加 `version` 列：法律版本/颁布年份
   - nullable=True（P0-3 修复：严禁在 migration 硬编码 UPDATE）
   - 由 knowledge-base/scripts/import_laws.py 跟法条一同入库（参考 Standard.version）
   - EvidenceLinker 校验时若 version 缺失 → raise EvidenceValidationError（应用原则 3）

2. 加 `aliases` 列：JSONB 数组，存同义词/缩写/英文名
   - default=[] + server_default='[]'（让历史 Law 行也能正常处理）
   - EvidenceLinker 匹配时遍历 code + name + aliases，解决 LLM 输出"中华人民共和国民法典"
     与 DB 存"民法典"的命名差异（P0-1 修复 silent failure）
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 加 version 列（nullable=True，P0-3 修复：不硬编码 UPDATE）
    op.add_column(
        "laws",
        sa.Column("version", sa.String(length=20), nullable=True),
    )

    # 2. 加 aliases 列（JSONB 数组，默认空数组）
    op.add_column(
        "laws",
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("laws", "aliases")
    op.drop_column("laws", "version")
