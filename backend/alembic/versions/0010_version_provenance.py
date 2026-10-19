"""Link chapter versions to the AI task or repair that produced them.

Revision ID: 0010_version_provenance
Revises: 0009_quality_issues
Create Date: 2026-10-19

Adds nullable ``ai_task_id`` and ``repair_candidate_id`` on ``chapter_versions``.
Does not rewrite ``0001``–``0009``. Existing snapshots keep null links.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_version_provenance"
down_revision: str | None = "0009_quality_issues"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot ALTER in a foreign key. Batch rebuilds the table and
    # copies the existing primary key, unique index, and check constraints.
    with op.batch_alter_table("chapter_versions") as batch:
        batch.add_column(sa.Column("ai_task_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("repair_candidate_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_chapter_versions_ai_task_id_ai_tasks",
            "ai_tasks",
            ["ai_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_chapter_versions_repair_candidate_id_quality_repair_candidates",
            "quality_repair_candidates",
            ["repair_candidate_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chapter_versions") as batch:
        batch.drop_constraint(
            "fk_chapter_versions_repair_candidate_id_quality_repair_candidates",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_chapter_versions_ai_task_id_ai_tasks",
            type_="foreignkey",
        )
        batch.drop_column("repair_candidate_id")
        batch.drop_column("ai_task_id")
