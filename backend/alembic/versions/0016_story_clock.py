"""Story-day columns, state dimensions, and optional time anchors.

Revision ID: 0016_story_clock
Revises: 0015_chronicle
Create Date: 2026-11-02

Discourse order stays chapter ``sort_order``. New day columns are empty on
old rows. ``time_precision`` is ``unknown`` and state ``dimension`` is
``custom``, so a missing parse is not a conflict. ``story_time_anchors``
starts empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_story_clock"
down_revision: str | None = "0015_chronicle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIMENSION = "dimension IN ('location', 'alive', 'injury', 'possession', 'identity', 'custom')"
_PRECISION = "time_precision IN ('day', 'month', 'season', 'unknown')"
_ANCHOR_KIND = "kind IN ('era', 'event', 'custom')"


def upgrade() -> None:
    with op.batch_alter_table("entity_states") as batch:
        batch.add_column(
            sa.Column(
                "dimension",
                sa.String(length=32),
                nullable=False,
                server_default="custom",
            )
        )
        batch.add_column(sa.Column("valid_from_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("valid_to_day", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "time_precision",
                sa.String(length=16),
                nullable=False,
                server_default="unknown",
            )
        )
        batch.create_check_constraint("ck_entity_states_dimension", _DIMENSION)
        batch.create_check_constraint("ck_entity_states_time_precision", _PRECISION)
    with op.batch_alter_table("story_events") as batch:
        batch.add_column(sa.Column("valid_from_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("valid_to_day", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "time_precision",
                sa.String(length=16),
                nullable=False,
                server_default="unknown",
            )
        )
        batch.create_check_constraint("ck_story_events_time_precision", _PRECISION)
    op.create_table(
        "story_time_anchors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_day", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_ANCHOR_KIND, name="ck_story_time_anchors_kind"),
        sa.CheckConstraint("sort_order >= 0", name="ck_story_time_anchors_sort_order"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_story_time_anchors_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_time_anchors"),
    )
    op.create_index("ix_story_time_anchors_novel_id", "story_time_anchors", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_story_time_anchors_novel_id", table_name="story_time_anchors")
    op.drop_table("story_time_anchors")
    with op.batch_alter_table("story_events") as batch:
        batch.drop_constraint("ck_story_events_time_precision", type_="check")
        batch.drop_column("time_precision")
        batch.drop_column("valid_to_day")
        batch.drop_column("valid_from_day")
    with op.batch_alter_table("entity_states") as batch:
        batch.drop_constraint("ck_entity_states_time_precision", type_="check")
        batch.drop_constraint("ck_entity_states_dimension", type_="check")
        batch.drop_column("time_precision")
        batch.drop_column("valid_to_day")
        batch.drop_column("valid_from_day")
        batch.drop_column("dimension")
