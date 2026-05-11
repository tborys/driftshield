"""add phase 3h teams schema

Revision ID: 20260511_02
Revises: 20260511_01
Create Date: 2026-05-11 18:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

from driftshield.db.hosted_schema_sql import build_phase3h_teams_drop_sql, build_phase3h_teams_sql


revision: str = "20260511_02"
down_revision: str | None = "20260511_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for statement in build_phase3h_teams_sql():
        op.execute(statement)


def downgrade() -> None:
    for statement in build_phase3h_teams_drop_sql():
        op.execute(statement)
