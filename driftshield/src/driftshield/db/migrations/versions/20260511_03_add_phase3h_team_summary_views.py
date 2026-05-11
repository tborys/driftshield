"""add phase 3h team summary views

Revision ID: 20260511_03
Revises: 20260511_02
Create Date: 2026-05-11 18:50:00.000000
"""

from collections.abc import Sequence

from alembic import op

from driftshield.db.hosted_schema_sql import (
    build_phase3h_team_pattern_sql,
    build_phase3h_team_recurrence_sql,
    build_phase3h_team_views_drop_sql,
)


revision: str = "20260511_03"
down_revision: str | None = "20260511_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for statement in build_phase3h_team_recurrence_sql():
        op.execute(statement)
    for statement in build_phase3h_team_pattern_sql():
        op.execute(statement)


def downgrade() -> None:
    for statement in build_phase3h_team_views_drop_sql():
        op.execute(statement)
