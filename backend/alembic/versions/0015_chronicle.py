"""Chronicle links on story events, and a queue for unconfirmed plans.

Revision ID: 0015_chronicle
Revises: 0014_guided_ideation
Create Date: 2026-10-23

Existing events keep their chapter, text, and evidence. New columns are empty.
``chapter_id`` may be null for events that are not placed in a chapter yet.
``chronicle_candidates`` starts empty and is not a second event table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_chronicle"
down_revision: str | None = "0014_guided_ideation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status IN ('pending', 'accepted', 'rejected', 'deferred')"
_CERTAINTY = "certainty IN ('confirmed', 'inferred', 'uncertain')"
_PROVIDER = "provider_mode IN ('mock', 'openai_compatible')"


def upgrade() -> None:
    with op.batch_alter_table("story_events") as batch:
        batch.alter_column(
            "chapter_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch.add_column(sa.Column("title", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("participant_entity_ids", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("story_arc_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("foreshadowing_id", sa.String(length=36), nullable=True))
        batch.create_check_constraint(
            "ck_story_events_sort_order",
            "sort_order IS NULL OR sort_order >= 0",
        )
        batch.create_foreign_key(
            "fk_story_events_story_arc_id_story_arcs",
            "story_arcs",
            ["story_arc_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_story_events_foreshadowing_id_foreshadowing",
            "foreshadowing",
            ["foreshadowing_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_story_events_story_arc_id", "story_events", ["story_arc_id"])
    op.create_index(
        "ix_story_events_foreshadowing_id",
        "story_events",
        ["foreshadowing_id"],
    )
    op.create_table(
        "chronicle_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("event_time_text", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("participant_entity_ids", sa.JSON(), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=True),
        sa.Column("story_arc_id", sa.String(length=36), nullable=True),
        sa.Column("foreshadowing_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("certainty", sa.String(length=32), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("model_config_id", sa.String(length=36), nullable=True),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("applied", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUS, name="ck_chronicle_candidates_status"),
        sa.CheckConstraint(_CERTAINTY, name="ck_chronicle_candidates_certainty"),
        sa.CheckConstraint(_PROVIDER, name="ck_chronicle_candidates_provider_mode"),
        sa.CheckConstraint(
            "sort_order IS NULL OR sort_order >= 0",
            name="ck_chronicle_candidates_sort_order",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_chronicle_candidates_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_chronicle_candidates_chapter_id_chapters",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["story_arc_id"],
            ["story_arcs.id"],
            name="fk_chronicle_candidates_story_arc_id_story_arcs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["foreshadowing_id"],
            ["foreshadowing.id"],
            name="fk_chronicle_candidates_foreshadowing_id_foreshadowing",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"],
            ["model_configs.id"],
            name="fk_chronicle_candidates_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chronicle_candidates"),
    )
    op.create_index(
        "ix_chronicle_candidates_novel_id_status",
        "chronicle_candidates",
        ["novel_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chronicle_candidates_novel_id_status",
        table_name="chronicle_candidates",
    )
    op.drop_table("chronicle_candidates")
    op.drop_index("ix_story_events_foreshadowing_id", table_name="story_events")
    op.drop_index("ix_story_events_story_arc_id", table_name="story_events")
    op.execute("DELETE FROM story_events WHERE chapter_id IS NULL")
    with op.batch_alter_table("story_events") as batch:
        batch.drop_constraint(
            "fk_story_events_foreshadowing_id_foreshadowing",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_story_events_story_arc_id_story_arcs",
            type_="foreignkey",
        )
        batch.drop_constraint("ck_story_events_sort_order", type_="check")
        batch.drop_column("foreshadowing_id")
        batch.drop_column("story_arc_id")
        batch.drop_column("participant_entity_ids")
        batch.drop_column("sort_order")
        batch.drop_column("title")
        batch.alter_column(
            "chapter_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
