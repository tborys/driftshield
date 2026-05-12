"""seed oss fallback installation

Revision ID: 20260512_02
Revises: 20260512_01
Create Date: 2026-05-12 20:25:00.000000
"""

from collections.abc import Sequence
import logging

from alembic import op
import sqlalchemy as sa

from driftshield.db.hosted_schema_sql import build_phase3h_oss_fallback_installation_seed_sql


revision: str = "20260512_02"
down_revision: str | None = "20260512_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOGGER = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    installation_insert_sql, consent_insert_sql, resolved_ids_sql = (
        build_phase3h_oss_fallback_installation_seed_sql()
    )
    op.execute(installation_insert_sql)
    op.execute(consent_insert_sql)
    resolved_ids = op.get_bind().execute(sa.text(resolved_ids_sql)).mappings().one()
    LOGGER.info("resolved oss fallback installation row uuid: %s", resolved_ids["installation_row_id"])
    LOGGER.info("resolved oss fallback consent row uuid: %s", resolved_ids["consent_record_id"])


def downgrade() -> None:
    raise NotImplementedError("forward-only; restore from snapshot per #163 AC5")
