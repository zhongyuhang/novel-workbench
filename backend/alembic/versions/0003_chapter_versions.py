"""Chapter version snapshots.

Revision ID: 0003_chapter_versions
Revises: 0002_catalog
Create Date: 2026-10-13

Snapshots store the canonical Tiptap JSON body (ADR-001) together with
``content_format_version`` so a later format migration can tell revisions apart.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_chapter_versions"
down_revision: str | None = "0002_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chapter_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_snapshot", sa.JSON(), nullable=False),
        sa.Column("content_format", sa.String(length=32), nullable=False),
        sa.Column("content_format_version", sa.Integer(), nullable=False),
        sa.Column("change_source", sa.String(length=32), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_source IN ('manual', 'ai_accepted', 'restore', 'import')",
            name="ck_chapter_versions_change_source",
        ),
        sa.CheckConstraint(
            "content_format = 'tiptap_json'",
            name="ck_chapter_versions_content_format",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_chapter_versions_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapter_versions"),
        sa.UniqueConstraint(
            "chapter_id",
            "revision",
            name="uq_chapter_versions_chapter_id_revision",
        ),
    )


def downgrade() -> None:
    op.drop_table("chapter_versions")
