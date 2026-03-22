import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExplanationPayloadResponse(BaseModel):
    reason: str
    confidence: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SessionProvenanceResponse(BaseModel):
    source_session_id: str | None = None
    source_path: str | None = None
    parser_version: str | None = None
    ingested_at: datetime | None = None


class SessionExplanationItemResponse(BaseModel):
    node_id: uuid.UUID
    payload: ExplanationPayloadResponse


class SessionExplanationsResponse(BaseModel):
    risk_explanations: dict[str, list[SessionExplanationItemResponse]] = Field(default_factory=dict)
    inflection_explanation: SessionExplanationItemResponse | None = None


class SessionSummary(BaseModel):
    id: uuid.UUID
    agent_id: str | None = None
    external_id: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    risk_flag_count: int = 0
    has_inflection: bool = False
    recurrence_level: str | None = None
    recurrence_probability: str | None = None
    recurrence_count: int | None = None
    provenance: SessionProvenanceResponse | None = None


class SessionDetail(SessionSummary):
    total_events: int = 0
    flagged_events: int = 0
    risk_summary: dict[str, int] = Field(default_factory=dict)
    explanations: SessionExplanationsResponse | None = None


class GraphNodeResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    action: str | None = None
    sequence_num: int
    risk_flags: list[str] = Field(default_factory=list)
    risk_explanations: dict[str, ExplanationPayloadResponse] = Field(default_factory=dict)
    is_inflection: bool = False
    inflection_explanation: ExplanationPayloadResponse | None = None
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    parent_node_id: uuid.UUID | None = None


class GraphEdgeResponse(BaseModel):
    source: uuid.UUID
    target: uuid.UUID


class GraphResponse(BaseModel):
    session_id: uuid.UUID
    provenance: SessionProvenanceResponse | None = None
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class IngestResponse(BaseModel):
    session_id: uuid.UUID
    total_events: int
    flagged_events: int
    has_inflection: bool
    status: str
    deduplicated: bool = False


class ConnectorResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    display_name: str
    root_path: str
    parser_name: str
    consent_state: str
    status: str
    watchable: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    watch_status: str
    last_scanned_at: datetime | None = None
    last_watch_heartbeat_at: datetime | None = None
    last_ingested_at: datetime | None = None
    last_seen_activity_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


class ConnectorListResponse(BaseModel):
    items: list[ConnectorResponse]


class ConnectorDiscoverRequest(BaseModel):
    project_dir: str | None = None


class ConnectorApproveRequest(BaseModel):
    mode: str = "once"


class ConnectorScanResponse(BaseModel):
    connector_id: uuid.UUID
    session_count: int
    newest_session_id: str | None = None
    newest_session_path: str | None = None
    newest_modified_at: datetime | None = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    per_page: int
    pages: int


class ValidationCreateRequest(BaseModel):
    target_type: str
    target_ref: str
    verdict: str
    reviewer: str
    confidence: float | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    shareable: bool = False


class ValidationResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    target_type: str
    target_ref: str
    verdict: str
    confidence: float | None = None
    reviewer: str
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    shareable: bool = False
    created_at: datetime


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
