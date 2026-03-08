"""add transcript provenance and dedupe support

Revision ID: 1c2f9f4b7d21
Revises: 7f2d6c4a9b31
Create Date: 2026-03-08 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1c2f9f4b7d21'
down_revision: Union[str, Sequence[str], None] = '7f2d6c4a9b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("transcript_hash", sa.String(length=64), nullable=True))
    op.add_column("sessions", sa.Column("source_session_id", sa.String(), nullable=True))
    op.add_column("sessions", sa.Column("source_path", sa.String(), nullable=True))
    op.add_column("sessions", sa.Column("parser_version", sa.String(), nullable=True))
    op.add_column("sessions", sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_sessions_transcript_hash_parser_version",
        "sessions",
        ["transcript_hash", "parser_version"],
        unique=True,
    )

    op.add_column("decision_nodes", sa.Column("risk_explanations", sa.JSON(), nullable=True))
    op.add_column("decision_nodes", sa.Column("inflection_explanation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_nodes", "inflection_explanation")
    op.drop_column("decision_nodes", "risk_explanations")
    op.drop_index("ix_sessions_transcript_hash_parser_version", table_name="sessions")
    op.drop_column("sessions", "ingested_at")
    op.drop_column("sessions", "parser_version")
    op.drop_column("sessions", "source_path")
    op.drop_column("sessions", "source_session_id")
    op.drop_column("sessions", "transcript_hash")
