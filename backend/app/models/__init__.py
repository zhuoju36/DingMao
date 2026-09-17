"""数据模型集中导入。

所有 ORM 模型在这里 import，确保 mapper 配置时所有类都已注册。
避免 string reference 在 mapper 初始化时找不到类。
"""

from app.models.base import Base, TimestampMixin
from app.models.consultation import (
    Consultation,
    ConsultationArtifact,
    ConsultationConclusion,
    ConsultationFact,
    ConsultationMessage,
    ConsultationScenario,
    ConsultationStatus,
)
from app.models.document import DocumentType, ProjectDocument
from app.models.knowledge import (
    BehaviorStandardMapping,
    Law,
    LawArticle,
    Standard,
    StandardClause,
)
from app.models.project import Project
from app.models.user import User, UserRole

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "UserRole",
    "Project",
    "ProjectDocument",
    "DocumentType",
    "Consultation",
    "ConsultationMessage",
    "ConsultationFact",
    "ConsultationConclusion",
    "ConsultationArtifact",
    "ConsultationScenario",
    "ConsultationStatus",
    "Law",
    "LawArticle",
    "Standard",
    "StandardClause",
    "BehaviorStandardMapping",
]
