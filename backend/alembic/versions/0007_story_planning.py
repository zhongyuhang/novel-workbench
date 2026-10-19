"""Story plan, chapter outlines, and scene cards.

Revision ID: 0007_story_planning
Revises: 0006_quality
Create Date: 2026-10-19

Does not create the unused hierarchical ``outlines`` sketch. Existing chapter
rows, revisions, and versions are left untouched. New tables start empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_story_planning"
down_revision: str | None = "0006_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status IN ('draft', 'confirmed', 'stale', 'archived')"


def upgrade() -> None:
    op.create_table(
        "story_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("logline", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("ending_intent", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS, name="ck_story_plans_status"),
        sa.CheckConstraint("revision >= 1", name="ck_story_plans_revision"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_story_plans_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_plans"),
        sa.UniqueConstraint("novel_id", name="uq_story_plans_novel_id"),
    )
    op.create_table(
        "chapter_outlines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("must_advance", sa.Text(), nullable=True),
        sa.Column("required_events", sa.Text(), nullable=True),
        sa.Column("allowed_reveals", sa.Text(), nullable=True),
        sa.Column("forbidden_reveals", sa.Text(), nullable=True),
        sa.Column("target_words", sa.Integer(), nullable=True),
        sa.Column("ending_hook", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS, name="ck_chapter_outlines_status"),
        sa.CheckConstraint("revision >= 1", name="ck_chapter_outlines_revision"),
        sa.CheckConstraint(
            "target_words IS NULL OR target_words >= 1",
            name="ck_chapter_outlines_target_words",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_chapter_outlines_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_chapter_outlines_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapter_outlines"),
        sa.UniqueConstraint("chapter_id", name="uq_chapter_outlines_chapter_id"),
    )
    op.create_index("ix_chapter_outlines_novel_id", "chapter_outlines", ["novel_id"])
    op.create_table(
        "scene_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("location_entity_id", sa.String(length=36), nullable=True),
        sa.Column("character_entity_ids", sa.JSON(), nullable=False),
        sa.Column("conflict", sa.Text(), nullable=True),
        sa.Column("turning_point", sa.Text(), nullable=True),
        sa.Column("expected_outcome", sa.Text(), nullable=True),
        sa.Column("must_convey", sa.Text(), nullable=True),
        sa.Column("must_not_reveal", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS, name="ck_scene_cards_status"),
        sa.CheckConstraint("revision >= 1", name="ck_scene_cards_revision"),
        sa.CheckConstraint("sort_order >= 0", name="ck_scene_cards_sort_order"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_scene_cards_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_scene_cards_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["location_entity_id"],
            ["story_entities.id"],
            name="fk_scene_cards_location_entity_id_story_entities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scene_cards"),
    )
    op.create_index("ix_scene_cards_novel_id", "scene_cards", ["novel_id"])
    op.create_index(
        "ix_scene_cards_chapter_id_sort_order",
        "scene_cards",
        ["chapter_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_scene_cards_chapter_id_sort_order", table_name="scene_cards")
    op.drop_index("ix_scene_cards_novel_id", table_name="scene_cards")
    op.drop_table("scene_cards")
    op.drop_index("ix_chapter_outlines_novel_id", table_name="chapter_outlines")
    op.drop_table("chapter_outlines")
    op.drop_table("story_plans")
