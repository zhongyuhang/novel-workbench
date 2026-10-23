"""Guided ideation sessions and a nullable novel core conflict.

Revision ID: 0014_guided_ideation
Revises: 0013_manuscript_material_sync
Create Date: 2026-10-23

Existing novels gain an empty core-conflict column. Ideation tables start empty.
Chapter text, revisions, and formal bible rows are unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_guided_ideation"
down_revision: str | None = "0013_manuscript_material_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION_KIND = "kind IN ('guided', 'world', 'character')"
_SESSION_STATUS = "status IN ('collecting', 'generated')"
_PROVIDER_MODE = "provider_mode IN ('mock', 'openai_compatible')"
_CANDIDATE_KIND = (
    "candidate_kind IN ("
    "'work_direction', 'world_setting', 'character_card', "
    "'character_relation', 'character_arc'"
    ")"
)
_CANDIDATE_STATUS = "status IN ('pending', 'accepted', 'rejected', 'deferred')"


def upgrade() -> None:
    with op.batch_alter_table("novels") as batch:
        batch.add_column(sa.Column("core_conflict", sa.Text(), nullable=True))
    op.create_table(
        "ideation_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("model_config_id", sa.String(length=36), nullable=True),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_SESSION_KIND, name="ck_ideation_sessions_kind"),
        sa.CheckConstraint(_SESSION_STATUS, name="ck_ideation_sessions_status"),
        sa.CheckConstraint("step_index >= 0", name="ck_ideation_sessions_step_index"),
        sa.CheckConstraint(_PROVIDER_MODE, name="ck_ideation_sessions_provider_mode"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_ideation_sessions_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"],
            ["model_configs.id"],
            name="fk_ideation_sessions_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ideation_sessions"),
    )
    op.create_index("ix_ideation_sessions_novel_id", "ideation_sessions", ["novel_id"])
    op.create_table(
        "ideation_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("applied", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_CANDIDATE_KIND, name="ck_ideation_candidates_kind"),
        sa.CheckConstraint(_CANDIDATE_STATUS, name="ck_ideation_candidates_status"),
        sa.CheckConstraint("sort_order >= 0", name="ck_ideation_candidates_sort_order"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ideation_sessions.id"],
            name="fk_ideation_candidates_session_id_ideation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_ideation_candidates_novel_id_novels",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ideation_candidates"),
    )
    op.create_index("ix_ideation_candidates_session_id", "ideation_candidates", ["session_id"])
    op.create_index(
        "ix_ideation_candidates_novel_id_status",
        "ideation_candidates",
        ["novel_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ideation_candidates_novel_id_status", table_name="ideation_candidates")
    op.drop_index("ix_ideation_candidates_session_id", table_name="ideation_candidates")
    op.drop_table("ideation_candidates")
    op.drop_index("ix_ideation_sessions_novel_id", table_name="ideation_sessions")
    op.drop_table("ideation_sessions")
    with op.batch_alter_table("novels") as batch:
        batch.drop_column("core_conflict")
