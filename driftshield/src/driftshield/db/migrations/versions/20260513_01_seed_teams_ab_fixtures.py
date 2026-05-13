"""seed teams alpha beta fixtures

Revision ID: 20260513_01
Revises: 20260512_02
Create Date: 2026-05-13 12:20:00.000000
"""

from collections.abc import Sequence
import logging

from alembic import op
import sqlalchemy as sa

from driftshield.db.hosted_schema_sql import build_phase3h_teams_ab_fixture_seed_sql


revision: str = "20260513_01"
down_revision: str | None = "20260512_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOGGER = logging.getLogger("alembic.runtime.migration")

# Keep the hard-coded row UUIDs aligned with the public Teams API fixture contract.


def upgrade() -> None:
    *seed_sql, resolved_ids_sql = build_phase3h_teams_ab_fixture_seed_sql()
    for statement in seed_sql:
        op.execute(statement)
    resolved_ids = op.get_bind().execute(sa.text(resolved_ids_sql)).mappings().one()
    for key, value in resolved_ids.items():
        LOGGER.info("resolved teams fixture %s: %s", key, value)


def downgrade() -> None:
    raise NotImplementedError("forward-only; restore from snapshot per #26 AC5")
