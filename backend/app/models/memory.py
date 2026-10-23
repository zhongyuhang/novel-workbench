"""Formal story memory and the proposals that may change it.

Analysis writes proposals only. Formal rows change when a person accepts a proposal.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class StoryEntity(Base):
    __tablename__ = "story_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character', 'location', 'organization', 'item', 'rule', 'other')",
            name="ck_story_entities_entity_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'unknown')",
            name="ck_story_entities_status",
        ),
        Index("ix_story_entities_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_story_entities_novel_id_novels"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChapterSummary(Base):
    __tablename__ = "chapter_summaries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('current', 'stale', 'rejected')",
            name="ck_chapter_summaries_status",
        ),
        Index("ix_chapter_summaries_chapter_id", "chapter_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_chapter_summaries_chapter_id_chapters"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_facts: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryChangeProposal(Base):
    """A candidate memory change. pending and stale rows are not formal memory."""

    __tablename__ = "memory_change_proposals"
    __table_args__ = (
        CheckConstraint(
            "proposal_type IN ("
            "'entity_create', 'entity_update', 'entity_state', 'story_event', 'chapter_summary', "
            "'entity_relation', 'foreshadowing', 'setting_supplement', 'potential_conflict'"
            ")",
            name="ck_memory_change_proposals_proposal_type",
        ),
        CheckConstraint(
            "status IN ("
            "'pending', 'accepted', 'rejected', 'reverted', 'stale', 'deferred', 'intentional'"
            ")",
            name="ck_memory_change_proposals_status",
        ),
        CheckConstraint(
            "certainty IN ('confirmed', 'inferred', 'uncertain')",
            name="ck_memory_change_proposals_certainty",
        ),
        Index("ix_memory_change_proposals_novel_id", "novel_id"),
        Index("ix_memory_change_proposals_source_chapter_id", "source_chapter_id"),
        Index("ix_memory_change_proposals_novel_id_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_memory_change_proposals_novel_id_novels"),
        nullable=False,
    )
    source_chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "chapters.id",
            name="fk_memory_change_proposals_source_chapter_id_chapters",
        ),
        nullable=False,
    )
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    certainty: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityState(Base):
    __tablename__ = "entity_states"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('manual', 'ai_proposal', 'import')",
            name="ck_entity_states_source_type",
        ),
        Index("ix_entity_states_entity_id", "entity_id"),
        Index("ix_entity_states_chapter_id", "chapter_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("story_entities.id", name="fk_entity_states_entity_id_story_entities"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_entity_states_chapter_id_chapters"),
        nullable=False,
    )
    source_revision: Mapped[int | None] = mapped_column(Integer)
    proposal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "memory_change_proposals.id",
            name="fk_entity_states_proposal_id_memory_change_proposals",
        ),
    )
    state_data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from_text: Mapped[str | None] = mapped_column(String(200))
    valid_until_text: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryEvent(Base):
    __tablename__ = "story_events"
    __table_args__ = (
        CheckConstraint(
            "certainty IN ('confirmed', 'inferred', 'uncertain')",
            name="ck_story_events_certainty",
        ),
        Index("ix_story_events_novel_id", "novel_id"),
        Index("ix_story_events_chapter_id", "chapter_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_story_events_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_story_events_chapter_id_chapters"),
        nullable=False,
    )
    source_revision: Mapped[int | None] = mapped_column(Integer)
    proposal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "memory_change_proposals.id",
            name="fk_story_events_proposal_id_memory_change_proposals",
        ),
    )
    event_time_text: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    participants: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    certainty: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityRelation(Base):
    """A directed link between two entities in the same novel.

    Story time, source chapter, and evidence may be empty. Empty time does not
    block writing. ``storyline`` is an optional label; there is no story-arc table.
    """

    __tablename__ = "entity_relations"
    __table_args__ = (
        CheckConstraint(
            "from_entity_id != to_entity_id",
            name="ck_entity_relations_distinct_ends",
        ),
        CheckConstraint(
            "status IN ('active', 'ended', 'unknown')",
            name="ck_entity_relations_status",
        ),
        Index("ix_entity_relations_novel_id", "novel_id"),
        Index("ix_entity_relations_from_entity_id", "from_entity_id"),
        Index("ix_entity_relations_to_entity_id", "to_entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_entity_relations_novel_id_novels"),
        nullable=False,
    )
    from_entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("story_entities.id", name="fk_entity_relations_from_entity_id_story_entities"),
        nullable=False,
    )
    to_entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("story_entities.id", name="fk_entity_relations_to_entity_id_story_entities"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    story_time_text: Mapped[str | None] = mapped_column(String(200))
    storyline: Mapped[str | None] = mapped_column(String(80))
    source_chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_entity_relations_source_chapter_id_chapters"),
    )
    source_revision: Mapped[int | None] = mapped_column(Integer)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
