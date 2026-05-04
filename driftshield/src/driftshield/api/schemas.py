import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExplanationPayloadResponse(BaseModel):
    reason: str
    confidence: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SessionProvenanceResponse(BaseModel):
    source_type: str | None = None
    source_session_id: str | None = None
    source_path: str | None = None
    parser_version: str | None = None
    transcript_hash: str | None = None
    ingested_at: datetime | None = None
    integrity_policy_version: str | None = None
    integrity_schema_version: str | None = None
    integrity_evaluated_at: datetime | None = None
    evidence_counts: dict[str, int] = Field(default_factory=dict)


class IntegrityStatusResponse(BaseModel):
    integrity_schema_version: str | None = None
    trust_band: str | None = None
    structural_score: float | None = None
    semantic_score: float | None = None
    source_factor: float | None = None
    pattern_integrity_score: float | None = None
    final_learning_weight: float | None = None
    integrity_reasons: list[str] = Field(default_factory=list)
    requires_review: bool | None = None
    integrity_evaluated_at: datetime | None = None
    integrity_policy_version: str | None = None
    evidence_counts: dict[str, int] = Field(default_factory=dict)
    pattern_integrity_note: str | None = None


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
    provenance: SessionProvenanceResponse | None = None
    integrity_status: IntegrityStatusResponse | None = None


class SignatureMatchSummaryResponse(BaseModel):
    status: str | None = None
    primary_mechanism_id: str | None = None
    matched_mechanism_ids: list[str] = Field(default_factory=list)
    match_count: int | None = None
    summary: str | None = None
    raw: dict[str, Any] | None = None


class SessionDetail(SessionSummary):
    total_events: int = 0
    flagged_events: int = 0
    risk_summary: dict[str, int] = Field(default_factory=dict)
    explanations: SessionExplanationsResponse | None = None
    signature_match: SignatureMatchSummaryResponse | None = None
    canonical_analysis: dict[str, Any] | None = None


class GraphNodeResponse(BaseModel):
    id: uuid.UUID
    node_kind: str | None = None
    event_type: str
    action: str | None = None
    summary: str | None = None
    confidence: float | None = None
    sequence_num: int
    risk_flags: list[str] = Field(default_factory=list)
    risk_explanations: dict[str, ExplanationPayloadResponse] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    is_inflection: bool = False
    inflection_explanation: ExplanationPayloadResponse | None = None
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    parent_node_id: uuid.UUID | None = None
    parent_node_ids: list[uuid.UUID] = Field(default_factory=list)
    lineage_ambiguities: list[str] = Field(default_factory=list)


class GraphEdgeResponse(BaseModel):
    source: uuid.UUID
    target: uuid.UUID
    relationship: str = "explicit_parent"
    confidence: float = 1.0
    inferred: bool = False
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


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


class BehaviourSubjectCreateRequest(BaseModel):
    subject_type: str
    pattern_reference: str
    trust_band: str
    surface: str
    session_id: uuid.UUID | None = None
    first_exposed_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None


class BehaviourEventCreateRequest(BaseModel):
    subject_id: uuid.UUID
    event_type: str
    actor_id: str | None = None
    originating_session_id: str | None = None
    linked_session_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None


class BehaviourSubjectResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID | None = None
    subject_type: str
    pattern_reference: str
    trust_band: str
    surface: str
    first_exposed_at: datetime
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    tracking_status: str
    follow_up_status: str
    event_counts: dict[str, int] = Field(default_factory=dict)


class BehaviourEventResponse(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    occurred_at: datetime
    event_type: str
    actor_id: str | None = None
    originating_session_id: str | None = None
    linked_session_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class GeneratedReportResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    generated_at: datetime
    report_type: str
    content_markdown: str | None = None
    content_json: dict[str, Any] | None = None
    generated_by: str | None = None


class ForensicCaseResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    state: str
    report_id: uuid.UUID | None = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    review_refs: list[str] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ForensicWorkflowResponse(BaseModel):
    session_id: uuid.UUID
    ingest_status: str
    deduplicated: bool = False
    parser_name: str
    source_path: str | None = None
    report: GeneratedReportResponse
    forensic_case: ForensicCaseResponse


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


class ForensicFeedbackCreateRequest(BaseModel):
    target_kind: str
    target_ref: str
    category: str
    outcome: str
    reviewer: str
    report_id: uuid.UUID | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None
    suggested_failure_family: str | None = None
    problem_detail: str | None = None
    shareable: bool = False


class ForensicFeedbackResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    target_kind: str
    target_ref: str
    category: str
    outcome: str
    verdict: str
    reviewer: str
    report_id: uuid.UUID | None = None
    confidence: float | None = None
    notes: str | None = None
    suggested_failure_family: str | None = None
    problem_detail: str | None = None
    shareable: bool = False
    created_at: datetime


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
