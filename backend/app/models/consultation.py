"""律师问诊对话模型 - 结构化多轮事实采集。"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project  # noqa: F401


class ConsultationScenario(StrEnum):
    CONTRACT_REVIEW = "contract_review"   # 合同审查
    VARIATION = "variation"                # 变更扯皮


class ConsultationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Consultation(Base, TimestampMixin):
    """一次问诊会话。"""

    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    scenario: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ConsultationStatus.IN_PROGRESS.value, nullable=False, index=True
    )

    # 争议焦点（用户原话 + AI 提炼）
    dispute_summary_user: Mapped[str | None] = mapped_column(Text)
    dispute_summary_ai: Mapped[str | None] = mapped_column(Text)

    # 当前状态机节点
    current_step: Mapped[str] = mapped_column(String(50), default="init")
    state_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 关系 - 用 string forward ref 避免循环 import
    project: Mapped["Project"] = relationship(back_populates="consultations")
    messages: Mapped[list["ConsultationMessage"]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
        order_by="ConsultationMessage.created_at",
    )
    facts: Mapped[list["ConsultationFact"]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
    )
    conclusions: Mapped[list["ConsultationConclusion"]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["ConsultationArtifact"]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
    )


class ConsultationMessage(Base, TimestampMixin):
    """问诊对话的单条消息。"""

    __tablename__ = "consultation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 结构化附加信息（如事实采集卡、强条提示）
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    step_at_time: Mapped[str | None] = mapped_column(String(50))

    consultation: Mapped["Consultation"] = relationship(back_populates="messages")


class ConsultationFact(Base, TimestampMixin):
    """问诊过程中采集的事实卡片 - 🟦 用户事实的载体。"""

    __tablename__ = "consultation_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), index=True
    )

    fact_key: Mapped[str] = mapped_column(String(100), nullable=False)  # 事实键名
    fact_label: Mapped[str] = mapped_column(String(200), nullable=False)  # 人类可读标签
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    fact_value_type: Mapped[str] = mapped_column(String(20), default="text")  # text/number/date/enum/json

    # 来源溯源
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("consultation_messages.id"))
    source_type: Mapped[str] = mapped_column(String(20), default="user_input")
    confidence: Mapped[float] = mapped_column(default=1.0)  # 用户直接输入为 1.0

    consultation: Mapped["Consultation"] = relationship(back_populates="facts")


class ConsultationConclusion(Base, TimestampMixin):
    """问诊结论 - 包含 🟦事实 + 🟨法条 + 🟥强条 三源。"""

    __tablename__ = "consultation_conclusions"

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), index=True
    )

    # 结论等级
    level: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # green=可控 / yellow=黄区 / red=红线

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 三源证据（JSONB 数组）
    fact_refs: Mapped[list[int]] = mapped_column(JSONB, default=list)        # 关联 fact id 列表
    law_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)         # [{code, article, version, effective_date}]
    standard_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)   # [{code, clause, version, is_mandatory}]

    # 推理链（LLM 生成但用户可复核）
    reasoning_chain: Mapped[str | None] = mapped_column(Text)
    counter_arguments: Mapped[str | None] = mapped_column(Text)  # 反例/例外

    consultation: Mapped["Consultation"] = relationship(back_populates="conclusions")


class ConsultationArtifact(Base, TimestampMixin):
    """问诊产出物 - 文书草稿。"""

    __tablename__ = "consultation_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), index=True
    )

    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # variation_order / claim_report / supervisor_notice / correspondence / review_memo

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # Jinja2 渲染后的最终内容

    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # 填充字段

    file_path: Mapped[str | None] = mapped_column(String(500))  # 生成的 docx/pdf 路径

    consultation: Mapped["Consultation"] = relationship(back_populates="artifacts")
