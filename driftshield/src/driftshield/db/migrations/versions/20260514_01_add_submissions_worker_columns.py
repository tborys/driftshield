"""add submissions worker columns

Revision ID: 20260514_01
Revises: 20260513_01
Create Date: 2026-05-14 06:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260514_01"
down_revision: str | None = "20260513_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "submissions",
        sa.Column("claimed_by", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "claimed_by")
    op.drop_column("submissions", "attempt_count")
