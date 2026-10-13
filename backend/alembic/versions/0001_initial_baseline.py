"""Baseline with no business tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-13

"""

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Later milestones add novels, chapters, and the other business tables.
    # This revision only establishes the Alembic version chain.
    return None


def downgrade() -> None:
    return None
