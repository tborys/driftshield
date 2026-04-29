"""add behaviour event tables

Revision ID: c3d9e4f1a2b5
Revises: b7c1e3d5f6a2
Create Date: 2026-04-29 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d9e4f1a2b5"
down_revision: str | None = "b7c1e3d5f6a2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "behaviour_event_subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("pattern_reference", sa.String(), nullable=False),
        sa.Column("trust_band", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column("first_exposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_behaviour_event_subjects_pattern_reference",
        "behaviour_event_subjects",
        ["pattern_reference"],
        unique=False,
    )
    op.create_index(
        "ix_behaviour_event_subjects_session_id",
        "behaviour_event_subjects",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "behaviour_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("originating_session_id", sa.String(), nullable=True),
        sa.Column("linked_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["linked_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["behaviour_event_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_behaviour_events_event_type_linked_session",
        "behaviour_events",
        ["event_type", "linked_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_behaviour_events_subject_id_occurred_at",
        "behaviour_events",
        ["subject_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_behaviour_events_subject_id_occurred_at", table_name="behaviour_events")
    op.drop_index("ix_behaviour_events_event_type_linked_session", table_name="behaviour_events")
    op.drop_table("behaviour_events")

    op.drop_index(
        "ix_behaviour_event_subjects_session_id",
        table_name="behaviour_event_subjects",
    )
    op.drop_index(
        "ix_behaviour_event_subjects_pattern_reference",
        table_name="behaviour_event_subjects",
    )
    op.drop_table("behaviour_event_subjects")
