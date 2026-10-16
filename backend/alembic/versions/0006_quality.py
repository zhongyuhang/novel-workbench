"""Foreshadowing and optional writing goals.

Revision ID: 0006_quality
Revises: 0005_memory
Create Date: 2026-10-16

Conflict hints are not a table. Checks only read confirmed facts and chapter text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_quality"
down_revision: str | None = "0005_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "foreshadowing",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("introduced_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payoff_chapter_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'planned', 'resolved', 'abandoned', 'uncertain')",
            name="ck_foreshadowing_status",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_foreshadowing_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["introduced_chapter_id"],
            ["chapters.id"],
            name="fk_foreshadowing_introduced_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["payoff_chapter_id"],
            ["chapters.id"],
            name="fk_foreshadowing_payoff_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_foreshadowing"),
    )
    op.create_index("ix_foreshadowing_novel_id", "foreshadowing", ["novel_id"])
    op.create_index(
        "ix_foreshadowing_novel_id_status",
        "foreshadowing",
        ["novel_id", "status"],
    )
    op.create_table(
        "writing_goals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("target_words", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target_words >= 1", name="ck_writing_goals_target_words"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_writing_goals_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_writing_goals"),
        sa.UniqueConstraint("novel_id", name="uq_writing_goals_novel_id"),
    )


def downgrade() -> None:
    op.drop_table("writing_goals")
    op.drop_index("ix_foreshadowing_novel_id_status", table_name="foreshadowing")
    op.drop_index("ix_foreshadowing_novel_id", table_name="foreshadowing")
    op.drop_table("foreshadowing")
