"""add hosted submission schema

Revision ID: 20260511_01
Revises: c3d9e4f1a2b5
Create Date: 2026-05-11 18:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

from driftshield.db.hosted_schema_sql import build_hosted_base_drop_sql, build_hosted_base_sql


revision: str = "20260511_01"
down_revision: str | None = "c3d9e4f1a2b5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for statement in build_hosted_base_sql():
        op.execute(statement)


def downgrade() -> None:
    for statement in build_hosted_base_drop_sql():
        op.execute(statement)
