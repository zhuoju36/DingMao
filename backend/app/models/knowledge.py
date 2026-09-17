"""知识库模型 - 法条、强条、行为-强条映射。"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Law(Base, TimestampMixin):
    """法律法规。"""

    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 例如: 中华人民共和国民法典

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # civil / construction / bidding / safety / administrative

    issuing_org: Mapped[str | None] = mapped_column(String(200))
    effective_date: Mapped["str | None"] = mapped_column(String(10))  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/replaced/abolished
    replaced_by: Mapped[str | None] = mapped_column(String(64))

    # 全文检索向量（PG tsvector，由触发器或应用层维护）
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    articles: Mapped[list["LawArticle"]] = relationship(  # noqa: F821
        back_populates="law",
        cascade="all, delete-orphan",
        order_by="LawArticle.article_no",
    )


class LawArticle(Base, TimestampMixin):
    """法条。"""

    __tablename__ = "law_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id", ondelete="CASCADE"), index=True)

    article_no: Mapped[str] = mapped_column(String(20), nullable=False)
    # 例如: 第五百七十七条

    content: Mapped[str] = mapped_column(Text, nullable=False)
    paragraph: Mapped[int] = mapped_column(Integer, default=1)  # 第几款
    item: Mapped[str | None] = mapped_column(String(20))  # 第几项

    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    law = relationship("Law", back_populates="articles")


class Standard(Base, TimestampMixin):
    """国家强制性标准。MVP 仅入库 38 本通用规范。"""

    __tablename__ = "standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 例如: GB 55001-2022

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # general / concrete / steel / foundation / safety / fire ...

    version: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(20), default="active")
    replaced_by: Mapped[str | None] = mapped_column(String(64))

    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    clauses: Mapped[list["StandardClause"]] = relationship(  # noqa: F821
        back_populates="standard",
        cascade="all, delete-orphan",
        order_by="StandardClause.clause_no",
    )


class StandardClause(Base, TimestampMixin):
    """强条/标准条款。"""

    __tablename__ = "standard_clauses"

    id: Mapped[int] = mapped_column(primary_key=True)
    standard_id: Mapped[int] = mapped_column(ForeignKey("standards.id", ondelete="CASCADE"), index=True)

    clause_no: Mapped[str] = mapped_column(String(20), nullable=False)
    # 例如: 4.1.1

    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # 行为标签（用于行为-强条匹配）
    behavior_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)

    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    standard = relationship("Standard", back_populates="clauses")


class BehaviorStandardMapping(Base, TimestampMixin):
    """行为-强条映射 - MVP 核心差异化资产。

    由工程人员人工标注 + AI 辅助校验。
    """

    __tablename__ = "behavior_standard_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 行为描述
    behavior_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 例如: concealed_work_no_acceptance

    behavior_description: Mapped[str] = mapped_column(Text, nullable=False)
    # 例如: 隐蔽工程未经验收进入下道工序

    behavior_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)

    # 关联强条
    clause_id: Mapped[int] = mapped_column(
        ForeignKey("standard_clauses.id", ondelete="CASCADE"), index=True
    )

    # 关联法条（可选）
    related_article_id: Mapped[int | None] = mapped_column(ForeignKey("law_articles.id"))

    # 风险等级
    risk_level: Mapped[str] = mapped_column(String(10), default="yellow", index=True)

    # 法律后果描述
    legal_consequence: Mapped[str | None] = mapped_column(Text)

    # 标注信息
    annotated_by: Mapped[str] = mapped_column(String(50), default="human")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
