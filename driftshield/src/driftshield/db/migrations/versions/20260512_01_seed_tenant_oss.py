"""seed tenant oss

Revision ID: 20260512_01
Revises: 20260511_03
Create Date: 2026-05-12 09:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

from driftshield.db.hosted_schema_sql import (
    build_phase3h_tenant_oss_seed_delete_sql,
    build_phase3h_tenant_oss_seed_sql,
)


revision: str = "20260512_01"
down_revision: str | None = "20260511_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for statement in build_phase3h_tenant_oss_seed_sql():
        op.execute(statement)


def downgrade() -> None:
    for statement in build_phase3h_tenant_oss_seed_delete_sql():
        op.execute(statement)
