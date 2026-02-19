import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, JSON, Boolean, Integer, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DecisionNodeModel(Base):
    __tablename__ = "decision_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("decision_nodes.id"), nullable=True, index=True
    )
    sequence_num: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Risk flags
    assumption_mutation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    policy_divergence: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    constraint_violation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    context_contamination: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    coverage_gap: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    is_inflection_node: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
