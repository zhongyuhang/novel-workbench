"""Novels, volumes, and chapters.

Revision ID: 0002_catalog
Revises: 0001_initial
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_catalog"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "novels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("genre", sa.String(length=100), nullable=True),
        sa.Column("synopsis", sa.Text(), nullable=True),
        sa.Column("style_guide", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_novels_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_novels"),
    )
    op.create_table(
        "volumes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_volumes_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_volumes"),
    )
    op.create_index(
        "ix_volumes_novel_id_sort_order",
        "volumes",
        ["novel_id", "sort_order"],
    )
    op.create_table(
        "chapters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("volume_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_format", sa.String(length=32), nullable=False),
        sa.Column("content_format_version", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('outline', 'draft', 'revised', 'final')",
            name="ck_chapters_status",
        ),
        sa.CheckConstraint(
            "content_format = 'tiptap_json'",
            name="ck_chapters_content_format",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_chapters_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["volume_id"],
            ["volumes.id"],
            name="fk_chapters_volume_id_volumes",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapters"),
    )
    op.create_index(
        "ix_chapters_novel_id_sort_order",
        "chapters",
        ["novel_id", "sort_order"],
    )
    op.create_index(
        "ix_chapters_volume_id_sort_order",
        "chapters",
        ["volume_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_chapters_volume_id_sort_order", table_name="chapters")
    op.drop_index("ix_chapters_novel_id_sort_order", table_name="chapters")
    op.drop_table("chapters")
    op.drop_index("ix_volumes_novel_id_sort_order", table_name="volumes")
    op.drop_table("volumes")
    op.drop_table("novels")
