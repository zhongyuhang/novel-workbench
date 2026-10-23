"""Guided design sessions. Candidates stay here until the author accepts one."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class IdeationSession(Base):
    """One question sequence for a novel. It does not store formal bible rows."""

    __tablename__ = "ideation_sessions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('guided', 'world', 'character')",
            name="ck_ideation_sessions_kind",
        ),
        CheckConstraint(
            "status IN ('collecting', 'generated')",
            name="ck_ideation_sessions_status",
        ),
        CheckConstraint("step_index >= 0", name="ck_ideation_sessions_step_index"),
        CheckConstraint(
            "provider_mode IN ('mock', 'openai_compatible')",
            name="ck_ideation_sessions_provider_mode",
        ),
        Index("ix_ideation_sessions_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_ideation_sessions_novel_id_novels"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    answers: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    model_config_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "model_configs.id",
            name="fk_ideation_sessions_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
    )
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdeationCandidate(Base):
    """A design candidate. Pending and deferred rows are not formal material."""

    __tablename__ = "ideation_candidates"
    __table_args__ = (
        CheckConstraint(
            "candidate_kind IN ("
            "'work_direction', 'world_setting', 'character_card', "
            "'character_relation', 'character_arc'"
            ")",
            name="ck_ideation_candidates_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'deferred')",
            name="ck_ideation_candidates_status",
        ),
        CheckConstraint("sort_order >= 0", name="ck_ideation_candidates_sort_order"),
        Index("ix_ideation_candidates_session_id", "session_id"),
        Index("ix_ideation_candidates_novel_id_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ideation_sessions.id",
            name="fk_ideation_candidates_session_id_ideation_sessions",
        ),
        nullable=False,
    )
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_ideation_candidates_novel_id_novels"),
        nullable=False,
    )
    candidate_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    applied: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
