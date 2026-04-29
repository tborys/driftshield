import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index(
            "ix_sessions_transcript_hash_parser_version",
            "transcript_hash",
            "parser_version",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transcript_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorModel(Base):
    __tablename__ = "connectors"
    __table_args__ = (
        Index("ix_connectors_connector_key", "connector_key", unique=True),
        Index("ix_connectors_source_type_status", "source_type", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    connector_key: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    parser_name: Mapped[str] = mapped_column(String, nullable=False)
    consent_state: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    watchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    watch_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="disabled",
        server_default="disabled",
    )
    last_watch_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConnectorSessionStateModel(Base):
    __tablename__ = "connector_session_states"
    __table_args__ = (
        Index(
            "ix_connector_session_states_connector_source_path",
            "connector_id",
            "source_path",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("connectors.id"),
        nullable=False,
        index=True,
    )
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    parser_name: Mapped[str] = mapped_column(String, nullable=False)
    session_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sessions.id"),
        nullable=True,
        index=True,
    )
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_transcript_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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

    assumption_mutation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    policy_divergence: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    constraint_violation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    context_contamination: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    coverage_gap: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    risk_explanations: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_inflection_node: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    inflection_explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ReportModel(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String, nullable=True)


class ForensicCaseModel(Base):
    __tablename__ = "forensic_cases"
    __table_args__ = (
        Index("ix_forensic_cases_session_id", "session_id", unique=True),
        Index("ix_forensic_cases_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("reports.id"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String, nullable=False)
    artifact_refs: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    review_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    audit_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalystValidationModel(Base):
    __tablename__ = "analyst_validations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_ref: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    shareable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BehaviourEventSubjectModel(Base):
    __tablename__ = "behaviour_event_subjects"
    __table_args__ = (
        Index("ix_behaviour_event_subjects_session_id", "session_id"),
        Index("ix_behaviour_event_subjects_pattern_reference", "pattern_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    pattern_reference: Mapped[str] = mapped_column(String, nullable=False)
    trust_band: Mapped[str] = mapped_column(String, nullable=False)
    surface: Mapped[str] = mapped_column(String, nullable=False)
    first_exposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BehaviourEventModel(Base):
    __tablename__ = "behaviour_events"
    __table_args__ = (
        Index("ix_behaviour_events_subject_id_occurred_at", "subject_id", "occurred_at"),
        Index(
            "ix_behaviour_events_event_type_linked_session",
            "event_type",
            "linked_session_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("behaviour_event_subjects.id"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    originating_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
