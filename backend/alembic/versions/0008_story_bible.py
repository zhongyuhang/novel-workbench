"""Entity relations and nullable state validity.

Revision ID: 0008_story_bible
Revises: 0007_story_planning
Create Date: 2026-10-19

Adds ``entity_relations`` and two nullable validity columns on ``entity_states``.
Does not rewrite ``0001``–``0007``. Existing rows keep their data; new columns
are null, so missing story time does not block older states.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_story_bible"
down_revision: str | None = "0007_story_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "entity_states",
        sa.Column("valid_from_text", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "entity_states",
        sa.Column("valid_until_text", sa.String(length=200), nullable=True),
    )
    op.create_table(
        "entity_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("from_entity_id", sa.String(length=36), nullable=False),
        sa.Column("to_entity_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("story_time_text", sa.String(length=200), nullable=True),
        sa.Column("storyline", sa.String(length=80), nullable=True),
        sa.Column("source_chapter_id", sa.String(length=36), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "from_entity_id != to_entity_id",
            name="ck_entity_relations_distinct_ends",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'unknown')",
            name="ck_entity_relations_status",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_entity_relations_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["from_entity_id"],
            ["story_entities.id"],
            name="fk_entity_relations_from_entity_id_story_entities",
        ),
        sa.ForeignKeyConstraint(
            ["to_entity_id"],
            ["story_entities.id"],
            name="fk_entity_relations_to_entity_id_story_entities",
        ),
        sa.ForeignKeyConstraint(
            ["source_chapter_id"],
            ["chapters.id"],
            name="fk_entity_relations_source_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_relations"),
    )
    op.create_index("ix_entity_relations_novel_id", "entity_relations", ["novel_id"])
    op.create_index(
        "ix_entity_relations_from_entity_id",
        "entity_relations",
        ["from_entity_id"],
    )
    op.create_index(
        "ix_entity_relations_to_entity_id",
        "entity_relations",
        ["to_entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_relations_to_entity_id", table_name="entity_relations")
    op.drop_index("ix_entity_relations_from_entity_id", table_name="entity_relations")
    op.drop_index("ix_entity_relations_novel_id", table_name="entity_relations")
    op.drop_table("entity_relations")
    op.drop_column("entity_states", "valid_until_text")
    op.drop_column("entity_states", "valid_from_text")
