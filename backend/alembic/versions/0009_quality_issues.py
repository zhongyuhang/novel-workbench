"""Evidence-backed quality issues and repair candidates.

Revision ID: 0009_quality_issues
Revises: 0008_story_bible
Create Date: 2026-10-19

Adds ``quality_issues`` and ``quality_repair_candidates``. Does not rewrite
``0001``–``0008``. Existing novels gain empty tables. Checks still do not
rewrite chapter text or formal memory.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_quality_issues"
down_revision: str | None = "0008_story_bible"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("issue_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("manuscript_snippet", sa.Text(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=True),
        sa.Column("location_note", sa.Text(), nullable=True),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("related_refs", sa.JSON(), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=True),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fixed_revision", sa.Integer(), nullable=True),
        sa.Column("recheck_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "issue_type IN ("
            "'fact_continuity', 'time_continuity', 'character_continuity', "
            "'foreshadowing', 'outline_execution', 'text_surface'"
            ")",
            name="ck_quality_issues_issue_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_quality_issues_severity",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_quality_issues_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'ignored', 'fixed', 'expired')",
            name="ck_quality_issues_status",
        ),
        sa.CheckConstraint(
            "evidence_status IN ('sufficient', 'insufficient')",
            name="ck_quality_issues_evidence_status",
        ),
        sa.CheckConstraint(
            "provider_mode IN ('rule', 'mock', 'openai_compatible')",
            name="ck_quality_issues_provider_mode",
        ),
        sa.CheckConstraint("recheck_count >= 0", name="ck_quality_issues_recheck_count"),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_quality_issues_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_quality_issues_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_issues"),
        sa.UniqueConstraint("novel_id", "fingerprint", name="uq_quality_issues_novel_fingerprint"),
    )
    op.create_index("ix_quality_issues_novel_id", "quality_issues", ["novel_id"])
    op.create_index(
        "ix_quality_issues_novel_id_status",
        "quality_issues",
        ["novel_id", "status"],
    )
    op.create_table(
        "quality_repair_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("apply_mode", sa.String(length=32), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        sa.Column("original_snippet", sa.Text(), nullable=False),
        sa.Column("replacement_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("diff_preview", sa.Text(), nullable=False),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "apply_mode IN ('replace_selection', 'append')",
            name="ck_quality_repair_candidates_apply_mode",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'conflict')",
            name="ck_quality_repair_candidates_status",
        ),
        sa.CheckConstraint(
            "provider_mode IN ('rule', 'mock', 'openai_compatible')",
            name="ck_quality_repair_candidates_provider_mode",
        ),
        sa.CheckConstraint(
            "target_revision >= 1",
            name="ck_quality_repair_candidates_target_revision",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["quality_issues.id"],
            name="fk_quality_repair_candidates_issue_id_quality_issues",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_quality_repair_candidates_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_quality_repair_candidates_chapter_id_chapters",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_repair_candidates"),
    )
    op.create_index(
        "ix_quality_repair_candidates_issue_id",
        "quality_repair_candidates",
        ["issue_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quality_repair_candidates_issue_id",
        table_name="quality_repair_candidates",
    )
    op.drop_table("quality_repair_candidates")
    op.drop_index("ix_quality_issues_novel_id_status", table_name="quality_issues")
    op.drop_index("ix_quality_issues_novel_id", table_name="quality_issues")
    op.drop_table("quality_issues")
