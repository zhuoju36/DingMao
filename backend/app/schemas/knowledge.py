"""知识库搜索相关 schemas。"""

from pydantic import BaseModel


class LawHit(BaseModel):
    """法条命中。"""

    law_id: int
    law_code: str
    law_name: str
    article_id: int
    article_no: str
    content: str
    keywords: list[str]
    effective_date: str | None


class StandardHit(BaseModel):
    """强条命中。"""

    standard_id: int
    standard_code: str
    standard_name: str
    clause_id: int
    clause_no: str
    content: str
    is_mandatory: bool
    behavior_tags: list[str]
    effective_date: str | None


class KnowledgeSearchResponse(BaseModel):
    query: str
    laws: list[LawHit]
    standards: list[StandardHit]
    total: int
