"""add analyst_validations table

Revision ID: 7f2d6c4a9b31
Revises: e0b85984643e
Create Date: 2026-02-25 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = '7f2d6c4a9b31'
down_revision: Union[str, Sequence[str], None] = 'e0b85984643e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create analyst validations table used by Session Review save/list flows."""
    op.create_table(
        "analyst_validations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("target_type", sa.String, nullable=False),
        sa.Column("target_ref", sa.String, nullable=False),
        sa.Column("verdict", sa.String, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("reviewer", sa.String, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("shareable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analyst_validations_session_id", "analyst_validations", ["session_id"])
    op.create_index("ix_analyst_validations_target_type", "analyst_validations", ["target_type"])
    op.create_index("ix_analyst_validations_verdict", "analyst_validations", ["verdict"])


def downgrade() -> None:
    """Drop analyst validations table."""
    op.drop_index("ix_analyst_validations_verdict", table_name="analyst_validations")
    op.drop_index("ix_analyst_validations_target_type", table_name="analyst_validations")
    op.drop_index("ix_analyst_validations_session_id", table_name="analyst_validations")
    op.drop_table("analyst_validations")
