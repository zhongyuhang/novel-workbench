"""Model config center fields: provider, default, test status, headers.

Revision ID: 0012_model_config_center
Revises: 0011_story_arcs
Create Date: 2026-10-20

Existing rows stay untested and are not the default. Ciphertext columns stay empty
until a key or custom headers are saved again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_model_config_center"
down_revision: str | None = "0011_story_arcs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_configs") as batch:
        batch.add_column(
            sa.Column("provider", sa.String(length=64), nullable=False, server_default="custom")
        )
        batch.add_column(sa.Column("encrypted_custom_headers", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "last_test_status",
                sa.String(length=32),
                nullable=False,
                server_default="untested",
            )
        )
        batch.add_column(sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_test_error_code", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_model_configs_last_test_status",
            "last_test_status IN ('untested', 'success', 'failed', 'stale')",
        )
    op.create_index(
        "uq_model_configs_one_default",
        "model_configs",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_configs_one_default", table_name="model_configs")
    with op.batch_alter_table("model_configs") as batch:
        batch.drop_constraint("ck_model_configs_last_test_status", type_="check")
        batch.drop_column("last_test_error_code")
        batch.drop_column("last_tested_at")
        batch.drop_column("last_test_status")
        batch.drop_column("is_default")
        batch.drop_column("encrypted_custom_headers")
        batch.drop_column("provider")
