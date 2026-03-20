"""add connectors table

Revision ID: 2d4f6b9e8c13
Revises: 1c2f9f4b7d21
Create Date: 2026-03-10 10:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2d4f6b9e8c13"
down_revision: str | None = "1c2f9f4b7d21"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_key", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("parser_name", sa.String(), nullable=False),
        sa.Column("consent_state", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("watchable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connectors_connector_key", "connectors", ["connector_key"], unique=True)
    op.create_index("ix_connectors_source_type", "connectors", ["source_type"], unique=False)
    op.create_index(
        "ix_connectors_source_type_status",
        "connectors",
        ["source_type", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_connectors_source_type_status", table_name="connectors")
    op.drop_index("ix_connectors_source_type", table_name="connectors")
    op.drop_index("ix_connectors_connector_key", table_name="connectors")
    op.drop_table("connectors")
