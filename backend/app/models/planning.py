"""Novel, chapter, and scene planning.

These rows are author plans. They are not manuscript revisions and not formal
memory. Only ``status='confirmed'`` may later be treated as a binding constraint.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base

_STATUS_CHECK = "status IN ('draft', 'confirmed', 'stale', 'archived')"


class StoryPlan(Base):
    """One novel-level outline. ``novels.synopsis`` stays a blurb, not this plan."""

    __tablename__ = "story_plans"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_story_plans_novel_id"),
        CheckConstraint(_STATUS_CHECK, name="ck_story_plans_status"),
        CheckConstraint("revision >= 1", name="ck_story_plans_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_story_plans_novel_id_novels"),
        nullable=False,
    )
    logline: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    ending_intent: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChapterOutline(Base):
    """Chapter intent. Independent from ``chapters.status`` and ``chapters.revision``."""

    __tablename__ = "chapter_outlines"
    __table_args__ = (
        UniqueConstraint("chapter_id", name="uq_chapter_outlines_chapter_id"),
        CheckConstraint(_STATUS_CHECK, name="ck_chapter_outlines_status"),
        CheckConstraint("revision >= 1", name="ck_chapter_outlines_revision"),
        CheckConstraint(
            "target_words IS NULL OR target_words >= 1",
            name="ck_chapter_outlines_target_words",
        ),
        Index("ix_chapter_outlines_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_chapter_outlines_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_chapter_outlines_chapter_id_chapters"),
        nullable=False,
    )
    goal: Mapped[str | None] = mapped_column(Text)
    must_advance: Mapped[str | None] = mapped_column(Text)
    required_events: Mapped[str | None] = mapped_column(Text)
    allowed_reveals: Mapped[str | None] = mapped_column(Text)
    forbidden_reveals: Mapped[str | None] = mapped_column(Text)
    target_words: Mapped[int | None] = mapped_column(Integer)
    ending_hook: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryArc(Base):
    """A named thread inside one novel. Not a manuscript revision."""

    __tablename__ = "story_arcs"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_story_arcs_status"),
        CheckConstraint("revision >= 1", name="ck_story_arcs_revision"),
        CheckConstraint("sort_order >= 0", name="ck_story_arcs_sort_order"),
        CheckConstraint(
            "arc_type IN ('main', 'subplot', 'character', 'other')",
            name="ck_story_arcs_arc_type",
        ),
        Index("ix_story_arcs_novel_id", "novel_id"),
        Index("ix_story_arcs_novel_id_sort_order", "novel_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_story_arcs_novel_id_novels"),
        nullable=False,
    )
    arc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VolumeOutline(Base):
    """One outline per volume. Its revision is not ``volumes`` or chapter revision."""

    __tablename__ = "volume_outlines"
    __table_args__ = (
        UniqueConstraint("volume_id", name="uq_volume_outlines_volume_id"),
        CheckConstraint(_STATUS_CHECK, name="ck_volume_outlines_status"),
        CheckConstraint("revision >= 1", name="ck_volume_outlines_revision"),
        Index("ix_volume_outlines_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_volume_outlines_novel_id_novels"),
        nullable=False,
    )
    volume_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("volumes.id", name="fk_volume_outlines_volume_id_volumes"),
        nullable=False,
    )
    goal: Mapped[str | None] = mapped_column(Text)
    key_events: Mapped[str | None] = mapped_column(Text)
    start_state: Mapped[str | None] = mapped_column(Text)
    end_state: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneCard(Base):
    """Ordered scene inside one chapter. People and places are entity ids only."""

    __tablename__ = "scene_cards"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_scene_cards_status"),
        CheckConstraint("revision >= 1", name="ck_scene_cards_revision"),
        CheckConstraint("sort_order >= 0", name="ck_scene_cards_sort_order"),
        Index("ix_scene_cards_novel_id", "novel_id"),
        Index("ix_scene_cards_chapter_id_sort_order", "chapter_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_scene_cards_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_scene_cards_chapter_id_chapters"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    goal: Mapped[str | None] = mapped_column(Text)
    location_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "story_entities.id",
            name="fk_scene_cards_location_entity_id_story_entities",
        ),
    )
    character_entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    conflict: Mapped[str | None] = mapped_column(Text)
    turning_point: Mapped[str | None] = mapped_column(Text)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    must_convey: Mapped[str | None] = mapped_column(Text)
    must_not_reveal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
