"""Story memory tables.

Revision ID: 0005_memory
Revises: 0004_ai
Create Date: 2026-10-16

Formal entities, states, events, and summaries change only when a proposal is accepted.
Pending proposals tied to an older chapter revision are marked stale, not applied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_memory"
down_revision: str | None = "0004_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "entity_type IN ('character', 'location', 'organization', 'item', 'rule', 'other')",
            name="ck_story_entities_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'unknown')",
            name="ck_story_entities_status",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_story_entities_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_entities"),
    )
    op.create_index("ix_story_entities_novel_id", "story_entities", ["novel_id"])
    op.create_table(
        "chapter_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_facts", sa.JSON(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('current', 'stale', 'rejected')",
            name="ck_chapter_summaries_status",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_chapter_summaries_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapter_summaries"),
    )
    op.create_index("ix_chapter_summaries_chapter_id", "chapter_summaries", ["chapter_id"])
    op.create_table(
        "memory_change_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("source_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("proposal_type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("certainty", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "proposal_type IN ("
            "'entity_create', 'entity_update', 'entity_state', 'story_event', 'chapter_summary'"
            ")",
            name="ck_memory_change_proposals_proposal_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'reverted', 'stale')",
            name="ck_memory_change_proposals_status",
        ),
        sa.CheckConstraint(
            "certainty IN ('confirmed', 'inferred', 'uncertain')",
            name="ck_memory_change_proposals_certainty",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_memory_change_proposals_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["source_chapter_id"],
            ["chapters.id"],
            name="fk_memory_change_proposals_source_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_change_proposals"),
    )
    op.create_index(
        "ix_memory_change_proposals_novel_id",
        "memory_change_proposals",
        ["novel_id"],
    )
    op.create_index(
        "ix_memory_change_proposals_source_chapter_id",
        "memory_change_proposals",
        ["source_chapter_id"],
    )
    op.create_index(
        "ix_memory_change_proposals_novel_id_status",
        "memory_change_proposals",
        ["novel_id", "status"],
    )
    op.create_table(
        "entity_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("state_data", sa.JSON(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('manual', 'ai_proposal', 'import')",
            name="ck_entity_states_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["story_entities.id"],
            name="fk_entity_states_entity_id_story_entities",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_entity_states_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["memory_change_proposals.id"],
            name="fk_entity_states_proposal_id_memory_change_proposals",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_states"),
    )
    op.create_index("ix_entity_states_entity_id", "entity_states", ["entity_id"])
    op.create_index("ix_entity_states_chapter_id", "entity_states", ["chapter_id"])
    op.create_table(
        "story_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("event_time_text", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("certainty", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "certainty IN ('confirmed', 'inferred', 'uncertain')",
            name="ck_story_events_certainty",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_story_events_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_story_events_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["memory_change_proposals.id"],
            name="fk_story_events_proposal_id_memory_change_proposals",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_events"),
    )
    op.create_index("ix_story_events_novel_id", "story_events", ["novel_id"])
    op.create_index("ix_story_events_chapter_id", "story_events", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_story_events_chapter_id", table_name="story_events")
    op.drop_index("ix_story_events_novel_id", table_name="story_events")
    op.drop_table("story_events")
    op.drop_index("ix_entity_states_chapter_id", table_name="entity_states")
    op.drop_index("ix_entity_states_entity_id", table_name="entity_states")
    op.drop_table("entity_states")
    op.drop_index(
        "ix_memory_change_proposals_novel_id_status",
        table_name="memory_change_proposals",
    )
    op.drop_index(
        "ix_memory_change_proposals_source_chapter_id",
        table_name="memory_change_proposals",
    )
    op.drop_index("ix_memory_change_proposals_novel_id", table_name="memory_change_proposals")
    op.drop_table("memory_change_proposals")
    op.drop_index("ix_chapter_summaries_chapter_id", table_name="chapter_summaries")
    op.drop_table("chapter_summaries")
    op.drop_index("ix_story_entities_novel_id", table_name="story_entities")
    op.drop_table("story_entities")
