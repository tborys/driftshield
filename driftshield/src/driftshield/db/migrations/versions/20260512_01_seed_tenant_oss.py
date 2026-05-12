"""seed tenant oss

Revision ID: 20260512_01
Revises: 20260511_03
Create Date: 2026-05-12 09:45:00.000000
"""

from collections.abc import Sequence
import logging

from alembic import op
import sqlalchemy as sa

from driftshield.db.hosted_schema_sql import build_phase3h_tenant_oss_seed_sql


revision: str = "20260512_01"
down_revision: str | None = "20260511_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOGGER = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    seed_insert_sql, select_sql = build_phase3h_tenant_oss_seed_sql()
    op.execute(seed_insert_sql)
    tenant_row_id = op.get_bind().execute(sa.text(select_sql)).scalar_one()
    LOGGER.info("resolved tenant-oss row uuid: %s", tenant_row_id)


def downgrade() -> None:
    raise NotImplementedError(
        "tenant-oss seed is forward-only; restore from the pre-execute Aurora snapshot recorded on #163 AC5"
    )
