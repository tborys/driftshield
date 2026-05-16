"""Convert all JSON columns to JSONB on Postgres.

Revision ID: 20260516_03
Revises: 20260512_02
Create Date: 2026-05-16

Postgres-native JSONB supports equality, DISTINCT, and GIN indexing.
Bare JSON does not. The live behaviour-events SELECT DISTINCT query
crashed against the auto-created and migrated schema because
behaviour_event_subjects.metadata_json (and friends) shipped as JSON.

Models now use `JSON().with_variant(JSONB(), 'postgresql')`. This
migration brings the live Postgres schema in sync. On non-Postgres
backends (SQLite tests, future SQLite fallback) this migration is
a no-op because the columns are already generic JSON there.
"""

from alembic import op


revision = "20260516_03"
down_revision = "20260512_02"
branch_labels = None
depends_on = None


_JSON_COLUMNS: list[tuple[str, str]] = [
    ("sessions", "metadata_json"),
    ("connectors", "metadata_json"),
    ("decision_nodes", "inputs"),
    ("decision_nodes", "outputs"),
    ("decision_nodes", "metadata_json"),
    ("decision_nodes", "risk_explanations"),
    ("decision_nodes", "inflection_explanation"),
    ("reports", "content_json"),
    ("forensic_cases", "artifact_refs"),
    ("forensic_cases", "review_refs"),
    ("forensic_cases", "audit_refs"),
    ("behaviour_event_subjects", "metadata_json"),
    ("behaviour_events", "metadata_json"),
    ("analyst_validations", "metadata_json"),
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _JSON_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE JSONB '
            f'USING {column}::text::jsonb'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _JSON_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE JSON '
            f'USING {column}::text::json'
        )
