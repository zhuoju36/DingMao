"""知识库搜索（W1 简化版：关键词 + ILIKE 搜索）。

W2 升级：
- 引入 tsvector 全文检索
- 引入行为-强条映射表
- 引入 embedding 语义检索（可选）
"""

from typing import Any

from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import Law, LawArticle, Standard, StandardClause


async def search_laws(db: AsyncSession, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """搜索法条（按关键词）。"""
    pattern = f"%{query}%"
    stmt = (
        select(LawArticle)
        .join(Law)
        .where(
            (Law.name.ilike(pattern))
            | (LawArticle.content.ilike(pattern))
            | (cast(LawArticle.keywords, Text).ilike(pattern))
        )
        .options(selectinload(LawArticle.law))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "law_id": a.law_id,
            "law_code": a.law.code,
            "law_name": a.law.name,
            "article_id": a.id,
            "article_no": a.article_no,
            "content": a.content,
            "keywords": a.keywords,
            "effective_date": a.law.effective_date,
        }
        for a in result.scalars().all()
    ]


async def search_standards(
    db: AsyncSession, query: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    """搜索强条/标准条款。"""
    pattern = f"%{query}%"
    stmt = (
        select(StandardClause)
        .join(Standard)
        .where(
            (Standard.name.ilike(pattern))
            | (StandardClause.content.ilike(pattern))
            | (cast(StandardClause.keywords, Text).ilike(pattern))
        )
        .options(selectinload(StandardClause.standard))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "standard_id": c.standard_id,
            "standard_code": c.standard.code,
            "standard_name": c.standard.name,
            "clause_id": c.id,
            "clause_no": c.clause_no,
            "content": c.content,
            "is_mandatory": c.is_mandatory,
            "behavior_tags": c.behavior_tags,
            "effective_date": c.standard.effective_date,
        }
        for c in result.scalars().all()
    ]
