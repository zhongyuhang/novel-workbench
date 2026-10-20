"""Story arcs and volume outlines.

Revision ID: 0011_story_arcs
Revises: 0010_version_provenance
Create Date: 2026-10-20

Adds empty ``story_arcs`` and ``volume_outlines`` tables. Does not rewrite
``0001``–``0010``. Existing chapters, revisions, and versions stay as they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_story_arcs"
down_revision: str | None = "0010_version_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status IN ('draft', 'confirmed', 'stale', 'archived')"
_ARC_TYPE = "arc_type IN ('main', 'subplot', 'character', 'other')"


def upgrade() -> None:
    op.create_table(
        "story_arcs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("arc_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS, name="ck_story_arcs_status"),
        sa.CheckConstraint("revision >= 1", name="ck_story_arcs_revision"),
        sa.CheckConstraint("sort_order >= 0", name="ck_story_arcs_sort_order"),
        sa.CheckConstraint(_ARC_TYPE, name="ck_story_arcs_arc_type"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_story_arcs_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_arcs"),
    )
    op.create_index("ix_story_arcs_novel_id", "story_arcs", ["novel_id"])
    op.create_index(
        "ix_story_arcs_novel_id_sort_order",
        "story_arcs",
        ["novel_id", "sort_order"],
    )
    op.create_table(
        "volume_outlines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("volume_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("key_events", sa.Text(), nullable=True),
        sa.Column("start_state", sa.Text(), nullable=True),
        sa.Column("end_state", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS, name="ck_volume_outlines_status"),
        sa.CheckConstraint("revision >= 1", name="ck_volume_outlines_revision"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_volume_outlines_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["volume_id"],
            ["volumes.id"],
            name="fk_volume_outlines_volume_id_volumes",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_volume_outlines"),
        sa.UniqueConstraint("volume_id", name="uq_volume_outlines_volume_id"),
    )
    op.create_index("ix_volume_outlines_novel_id", "volume_outlines", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_volume_outlines_novel_id", table_name="volume_outlines")
    op.drop_table("volume_outlines")
    op.drop_index("ix_story_arcs_novel_id_sort_order", table_name="story_arcs")
    op.drop_index("ix_story_arcs_novel_id", table_name="story_arcs")
    op.drop_table("story_arcs")
