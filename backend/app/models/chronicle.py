"""Unconfirmed chronicle plans. Accept is what writes ``story_events``."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base

_STATUS = "status IN ('pending', 'accepted', 'rejected', 'deferred')"
_CERTAINTY = "certainty IN ('confirmed', 'inferred', 'uncertain')"
_PROVIDER = "provider_mode IN ('mock', 'openai_compatible')"


class ChronicleCandidate(Base):
    """One proposed event. It is not a second chronicle."""

    __tablename__ = "chronicle_candidates"
    __table_args__ = (
        CheckConstraint(_STATUS, name="ck_chronicle_candidates_status"),
        CheckConstraint(_CERTAINTY, name="ck_chronicle_candidates_certainty"),
        CheckConstraint(_PROVIDER, name="ck_chronicle_candidates_provider_mode"),
        CheckConstraint(
            "sort_order IS NULL OR sort_order >= 0",
            name="ck_chronicle_candidates_sort_order",
        ),
        Index("ix_chronicle_candidates_novel_id_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_chronicle_candidates_novel_id_novels"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_time_text: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int | None] = mapped_column(Integer)
    participants: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    participant_entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "chapters.id",
            name="fk_chronicle_candidates_chapter_id_chapters",
            ondelete="SET NULL",
        ),
    )
    story_arc_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "story_arcs.id",
            name="fk_chronicle_candidates_story_arc_id_story_arcs",
            ondelete="SET NULL",
        ),
    )
    foreshadowing_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "foreshadowing.id",
            name="fk_chronicle_candidates_foreshadowing_id_foreshadowing",
            ondelete="SET NULL",
        ),
    )
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    certainty: Mapped[str] = mapped_column(String(32), nullable=False)
    hint: Mapped[str | None] = mapped_column(Text)
    model_config_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "model_configs.id",
            name="fk_chronicle_candidates_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
    )
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    applied: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
