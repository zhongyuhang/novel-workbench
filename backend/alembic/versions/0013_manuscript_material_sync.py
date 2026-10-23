"""Manuscript and material sync fields.

Revision ID: 0013_manuscript_material_sync
Revises: 0012_model_config_center
Create Date: 2026-10-23

Foreshadowing keeps planting chapter and resolution status, and gains separate
text times. Existing quality issues are suspected findings. Existing story arcs
have no surface/hidden mark. Proposal checks grow to cover the new candidate
kinds and review states. Old rows stay valid.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_manuscript_material_sync"
down_revision: str | None = "0012_model_config_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PROPOSAL_TYPES = (
    "proposal_type IN ("
    "'entity_create', 'entity_update', 'entity_state', 'story_event', 'chapter_summary'"
    ")"
)
_NEW_PROPOSAL_TYPES = (
    "proposal_type IN ("
    "'entity_create', 'entity_update', 'entity_state', 'story_event', 'chapter_summary', "
    "'entity_relation', 'foreshadowing', 'setting_supplement', 'potential_conflict'"
    ")"
)
_OLD_PROPOSAL_STATUS = "status IN ('pending', 'accepted', 'rejected', 'reverted', 'stale')"
_NEW_PROPOSAL_STATUS = (
    "status IN ('pending', 'accepted', 'rejected', 'reverted', 'stale', 'deferred', 'intentional')"
)
_OLD_ISSUE_STATUS = "status IN ('pending', 'confirmed', 'ignored', 'fixed', 'expired')"
_NEW_ISSUE_STATUS = (
    "status IN ('pending', 'confirmed', 'ignored', 'fixed', 'expired', 'deferred', 'intentional')"
)


def upgrade() -> None:
    with op.batch_alter_table("foreshadowing") as batch:
        batch.add_column(sa.Column("event_time_text", sa.String(length=200), nullable=True))
        batch.add_column(
            sa.Column("character_discovered_text", sa.String(length=200), nullable=True)
        )
        batch.add_column(sa.Column("reader_revealed_text", sa.String(length=200), nullable=True))
    with op.batch_alter_table("quality_issues") as batch:
        batch.add_column(
            sa.Column(
                "finding_class",
                sa.String(length=32),
                nullable=False,
                server_default="suspected",
            )
        )
        batch.drop_constraint("ck_quality_issues_status", type_="check")
        batch.create_check_constraint("ck_quality_issues_status", _NEW_ISSUE_STATUS)
        batch.create_check_constraint(
            "ck_quality_issues_finding_class",
            "finding_class IN ('deterministic', 'suspected', 'creative_risk')",
        )
    with op.batch_alter_table("memory_change_proposals") as batch:
        batch.drop_constraint("ck_memory_change_proposals_proposal_type", type_="check")
        batch.create_check_constraint(
            "ck_memory_change_proposals_proposal_type",
            _NEW_PROPOSAL_TYPES,
        )
        batch.drop_constraint("ck_memory_change_proposals_status", type_="check")
        batch.create_check_constraint("ck_memory_change_proposals_status", _NEW_PROPOSAL_STATUS)
    with op.batch_alter_table("story_arcs") as batch:
        batch.add_column(sa.Column("thread_visibility", sa.String(length=16), nullable=True))
        batch.create_check_constraint(
            "ck_story_arcs_thread_visibility",
            "thread_visibility IS NULL OR thread_visibility IN ('surface', 'hidden')",
        )


def downgrade() -> None:
    with op.batch_alter_table("story_arcs") as batch:
        batch.drop_constraint("ck_story_arcs_thread_visibility", type_="check")
        batch.drop_column("thread_visibility")
    with op.batch_alter_table("memory_change_proposals") as batch:
        batch.drop_constraint("ck_memory_change_proposals_status", type_="check")
        batch.create_check_constraint("ck_memory_change_proposals_status", _OLD_PROPOSAL_STATUS)
        batch.drop_constraint("ck_memory_change_proposals_proposal_type", type_="check")
        batch.create_check_constraint(
            "ck_memory_change_proposals_proposal_type",
            _OLD_PROPOSAL_TYPES,
        )
    with op.batch_alter_table("quality_issues") as batch:
        batch.drop_constraint("ck_quality_issues_finding_class", type_="check")
        batch.drop_constraint("ck_quality_issues_status", type_="check")
        batch.create_check_constraint("ck_quality_issues_status", _OLD_ISSUE_STATUS)
        batch.drop_column("finding_class")
    with op.batch_alter_table("foreshadowing") as batch:
        batch.drop_column("reader_revealed_text")
        batch.drop_column("character_discovered_text")
        batch.drop_column("event_time_text")
