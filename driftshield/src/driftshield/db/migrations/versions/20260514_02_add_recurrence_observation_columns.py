"""add recurrence observation evaluation columns

Revision ID: 20260514_02
Revises: 20260514_01
Create Date: 2026-05-14 16:35:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260514_02"
down_revision: str | None = "20260514_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recurrence_observations", sa.Column("workflow_id", sa.Text(), nullable=True))
    op.add_column("recurrence_observations", sa.Column("mechanism_id", sa.Text(), nullable=True))
    op.add_column("recurrence_observations", sa.Column("trust_band", sa.Text(), nullable=True))
    op.add_column("recurrence_observations", sa.Column("confidence_band", sa.Text(), nullable=True))
    op.add_column("recurrence_observations", sa.Column("learning_weight", sa.Float(), nullable=True))
    op.add_column(
        "recurrence_observations",
        sa.Column("contributes_to_recurrence", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "recurrence_observations",
        sa.Column("supports_maturation", sa.Boolean(), nullable=True),
    )
    array_type: sa.types.TypeEngine
    if op.get_bind().dialect.name == "sqlite":
        array_type = sa.JSON()
    else:
        array_type = postgresql.ARRAY(sa.Text())
    op.add_column(
        "recurrence_observations",
        sa.Column("quarantine_reason_codes", array_type, nullable=True),
    )
    op.add_column(
        "recurrence_observations",
        sa.Column("signature_ids", array_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recurrence_observations", "signature_ids")
    op.drop_column("recurrence_observations", "quarantine_reason_codes")
    op.drop_column("recurrence_observations", "supports_maturation")
    op.drop_column("recurrence_observations", "contributes_to_recurrence")
    op.drop_column("recurrence_observations", "learning_weight")
    op.drop_column("recurrence_observations", "confidence_band")
    op.drop_column("recurrence_observations", "trust_band")
    op.drop_column("recurrence_observations", "mechanism_id")
    op.drop_column("recurrence_observations", "workflow_id")
