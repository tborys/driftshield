import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SessionSummary(BaseModel):
    id: uuid.UUID
    agent_id: str | None = None
    external_id: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    risk_flag_count: int = 0
    has_inflection: bool = False


class SessionDetail(SessionSummary):
    total_events: int = 0
    flagged_events: int = 0
    risk_summary: dict[str, int] = {}


class GraphNodeResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    action: str | None = None
    sequence_num: int
    risk_flags: list[str] = []
    is_inflection: bool = False
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    parent_node_id: uuid.UUID | None = None


class GraphEdgeResponse(BaseModel):
    source: uuid.UUID
    target: uuid.UUID


class GraphResponse(BaseModel):
    session_id: uuid.UUID
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class IngestResponse(BaseModel):
    session_id: uuid.UUID
    total_events: int
    flagged_events: int
    has_inflection: bool


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
