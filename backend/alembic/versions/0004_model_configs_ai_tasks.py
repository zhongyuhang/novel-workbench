"""Model configs and AI tasks.

Revision ID: 0004_ai
Revises: 0003_chapter_versions
Create Date: 2026-10-16

API keys are stored only as ciphertext in model_configs.secret_ref.
A completed ai_tasks row is a candidate, not an accepted chapter edit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ai"
down_revision: str | None = "0003_chapter_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("secret_ref", sa.Text(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider_type IN ('openai_compatible', 'mock')",
            name="ck_model_configs_provider_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_configs"),
    )
    op.create_index("ix_model_configs_is_enabled", "model_configs", ["is_enabled"])
    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_config_id", sa.String(length=36), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message_safe", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_ai_tasks_status",
        ),
        sa.CheckConstraint(
            "task_type IN ('continue', 'rewrite', 'polish', 'expand', 'shrink', 'proofread')",
            name="ck_ai_tasks_task_type",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('accepted', 'rejected')",
            name="ck_ai_tasks_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_ai_tasks_novel_id_novels",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name="fk_ai_tasks_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"],
            ["model_configs.id"],
            name="fk_ai_tasks_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_tasks"),
    )
    op.create_index("ix_ai_tasks_novel_id", "ai_tasks", ["novel_id"])
    op.create_index("ix_ai_tasks_chapter_id", "ai_tasks", ["chapter_id"])
    op.create_index("ix_ai_tasks_status", "ai_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_tasks_status", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_chapter_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_novel_id", table_name="ai_tasks")
    op.drop_table("ai_tasks")
    op.drop_index("ix_model_configs_is_enabled", table_name="model_configs")
    op.drop_table("model_configs")
