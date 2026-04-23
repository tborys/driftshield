"""add forensic cases table

Revision ID: b7c1e3d5f6a2
Revises: 9b3d7e1a4c2f
Create Date: 2026-04-23 14:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b7c1e3d5f6a2"
down_revision: str | None = "9b3d7e1a4c2f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forensic_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("artifact_refs", sa.JSON(), nullable=False),
        sa.Column("review_refs", sa.JSON(), nullable=False),
        sa.Column("audit_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forensic_cases_report_id", "forensic_cases", ["report_id"], unique=False)
    op.create_index("ix_forensic_cases_session_id", "forensic_cases", ["session_id"], unique=True)
    op.create_index("ix_forensic_cases_state", "forensic_cases", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_forensic_cases_state", table_name="forensic_cases")
    op.drop_index("ix_forensic_cases_session_id", table_name="forensic_cases")
    op.drop_index("ix_forensic_cases_report_id", table_name="forensic_cases")
    op.drop_table("forensic_cases")
