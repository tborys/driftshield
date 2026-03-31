"""remove recurrence tables from oss

Revision ID: 9b3d7e1a4c2f
Revises: 8f1a2b3c4d5e
Create Date: 2026-03-31 10:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9b3d7e1a4c2f"
down_revision: str | None = "8f1a2b3c4d5e"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "session_signatures" in tables:
        op.drop_table("session_signatures")

    if "recurrence_signatures" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("recurrence_signatures")}
        if "ix_recurrence_signatures_hash" in indexes:
            op.drop_index("ix_recurrence_signatures_hash", table_name="recurrence_signatures")
        op.drop_table("recurrence_signatures")


def downgrade() -> None:
    uuid_type: sa.types.TypeEngine
    matched_nodes_type: sa.types.TypeEngine
    if op.get_bind().dialect.name == "sqlite":
        uuid_type = sa.String(length=36)
        matched_nodes_type = sa.JSON()
    else:
        uuid_type = postgresql.UUID(as_uuid=True)
        matched_nodes_type = postgresql.ARRAY(postgresql.UUID(as_uuid=True))

    op.create_table(
        "recurrence_signatures",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("signature_hash", sa.String(length=64), nullable=False),
        sa.Column("pattern", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("severity", sa.String(), nullable=False, server_default="low"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signature_hash"),
    )
    op.create_index(
        "ix_recurrence_signatures_hash",
        "recurrence_signatures",
        ["signature_hash"],
        unique=False,
    )
    op.create_table(
        "session_signatures",
        sa.Column("session_id", uuid_type, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "signature_id",
            uuid_type,
            sa.ForeignKey("recurrence_signatures.id"),
            nullable=False,
        ),
        sa.Column("matched_nodes", matched_nodes_type, nullable=True),
        sa.PrimaryKeyConstraint("session_id", "signature_id"),
    )
