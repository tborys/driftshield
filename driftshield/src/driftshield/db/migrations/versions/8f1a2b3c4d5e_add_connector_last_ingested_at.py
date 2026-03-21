"""add connector watcher state

Revision ID: 8f1a2b3c4d5e
Revises: 2d4f6b9e8c13
Create Date: 2026-03-20 22:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8f1a2b3c4d5e"
down_revision: str | None = "2d4f6b9e8c13"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connectors",
        sa.Column("watch_status", sa.String(), nullable=False, server_default="disabled"),
    )
    op.add_column(
        "connectors",
        sa.Column("last_watch_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "connector_session_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "connector_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connectors.id"),
            nullable=False,
        ),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("parser_name", sa.String(), nullable=False),
        sa.Column(
            "session_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"),
            nullable=True,
        ),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_size_bytes", sa.Integer(), nullable=True),
        sa.Column("last_transcript_hash", sa.String(length=64), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_session_states_connector_id",
        "connector_session_states",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_session_states_session_model_id",
        "connector_session_states",
        ["session_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_session_states_connector_source_path",
        "connector_session_states",
        ["connector_id", "source_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_connector_session_states_connector_source_path",
        table_name="connector_session_states",
    )
    op.drop_index(
        "ix_connector_session_states_session_model_id",
        table_name="connector_session_states",
    )
    op.drop_index(
        "ix_connector_session_states_connector_id",
        table_name="connector_session_states",
    )
    op.drop_table("connector_session_states")

    op.drop_column("connectors", "last_error_at")
    op.drop_column("connectors", "last_ingested_at")
    op.drop_column("connectors", "last_watch_heartbeat_at")
    op.drop_column("connectors", "watch_status")
