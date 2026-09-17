"""知识库搜索路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.models.base import get_db
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeSearchResponse,
    LawHit,
    StandardHit,
)
from app.services import knowledge_search

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search(
    q: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    limit: int = 5,
) -> KnowledgeSearchResponse:
    """关键词搜索法条 + 强条。

    W1: 用 ILIKE 模糊匹配。W2 升级为 tsvector + 行为-强条映射。
    """
    laws_raw = await knowledge_search.search_laws(db, q, limit=limit)
    standards_raw = await knowledge_search.search_standards(db, q, limit=limit)

    laws = [LawHit(**law) for law in laws_raw]
    standards = [StandardHit(**std) for std in standards_raw]
    return KnowledgeSearchResponse(
        query=q,
        laws=laws,
        standards=standards,
        total=len(laws) + len(standards),
    )
