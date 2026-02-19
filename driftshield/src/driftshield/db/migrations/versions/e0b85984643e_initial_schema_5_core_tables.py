"""initial schema - 5 core tables

Revision ID: e0b85984643e
Revises:
Create Date: 2026-02-19 13:49:12.386883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


# revision identifiers, used by Alembic.
revision: str = 'e0b85984643e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the 5 core tables."""
    # Sessions
    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String, nullable=True),
        sa.Column("agent_id", sa.String, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("metadata_json", JSONB, nullable=True),
    )

    # Decision nodes
    op.create_table(
        "decision_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_node_id", UUID(as_uuid=True), sa.ForeignKey("decision_nodes.id"), nullable=True),
        sa.Column("sequence_num", sa.Integer, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=True),
        sa.Column("inputs", JSONB, nullable=True),
        sa.Column("outputs", JSONB, nullable=True),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("assumption_mutation", sa.Boolean, server_default="false", nullable=False),
        sa.Column("policy_divergence", sa.Boolean, server_default="false", nullable=False),
        sa.Column("constraint_violation", sa.Boolean, server_default="false", nullable=False),
        sa.Column("context_contamination", sa.Boolean, server_default="false", nullable=False),
        sa.Column("coverage_gap", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_inflection_node", sa.Boolean, server_default="false", nullable=False),
    )
    op.create_index("ix_decision_nodes_session_id", "decision_nodes", ["session_id"])
    op.create_index("ix_decision_nodes_parent_node_id", "decision_nodes", ["parent_node_id"])
    op.create_index("ix_decision_nodes_session_seq", "decision_nodes", ["session_id", "sequence_num"])

    # Recurrence signatures
    op.create_table(
        "recurrence_signatures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("signature_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("pattern", JSONB, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("severity", sa.String, nullable=False, server_default="low"),
    )
    op.create_index("ix_recurrence_signatures_hash", "recurrence_signatures", ["signature_hash"])

    # Session signatures (junction)
    op.create_table(
        "session_signatures",
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("signature_id", UUID(as_uuid=True), sa.ForeignKey("recurrence_signatures.id"), primary_key=True),
        sa.Column("matched_nodes", ARRAY(UUID(as_uuid=True)), nullable=True),
    )

    # Reports
    op.create_table(
        "reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_type", sa.String, nullable=False),
        sa.Column("content_markdown", sa.Text, nullable=True),
        sa.Column("content_json", JSONB, nullable=True),
        sa.Column("generated_by", sa.String, nullable=True),
    )
    op.create_index("ix_reports_session_id", "reports", ["session_id"])


def downgrade() -> None:
    """Drop all 5 core tables."""
    op.drop_table("reports")
    op.drop_table("session_signatures")
    op.drop_table("recurrence_signatures")
    op.drop_table("decision_nodes")
    op.drop_table("sessions")
