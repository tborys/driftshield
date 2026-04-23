import uuid
from datetime import datetime, timezone

from driftshield.api.schemas import (
    SessionSummary, GraphNodeResponse, GraphEdgeResponse,
    GraphResponse, PaginatedResponse, IngestResponse,
)


def test_session_summary_serialisation():
    s = SessionSummary(
        id=uuid.uuid4(),
        agent_id="test",
        status="completed",
        started_at=datetime.now(timezone.utc),
        risk_flag_count=3,
        has_inflection=True,
    )
    data = s.model_dump(mode="json")
    assert "id" in data
    assert data["risk_flag_count"] == 3


def test_graph_response_structure():
    node_id = uuid.uuid4()
    g = GraphResponse(
        session_id=uuid.uuid4(),
        nodes=[
            GraphNodeResponse(
                id=node_id,
                node_kind="tool_call",
                event_type="TOOL_CALL",
                action="read_file",
                summary="Read the target file.",
                sequence_num=1,
                risk_flags=[],
                evidence_refs=["event:test"],
                is_inflection=False,
                parent_node_ids=[],
                lineage_ambiguities=[],
            )
        ],
        edges=[
            GraphEdgeResponse(
                source=node_id,
                target=node_id,
                relationship="explicit_parent",
                confidence=1.0,
                inferred=False,
                evidence_refs=["event:test"],
            )
        ],
    )
    data = g.model_dump(mode="json")
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["action"] == "read_file"


def test_ingest_response():
    r = IngestResponse(
        session_id=uuid.uuid4(),
        total_events=10,
        flagged_events=2,
        has_inflection=True,
        status="created",
        deduplicated=False,
    )
    data = r.model_dump(mode="json")
    assert data["total_events"] == 10
    assert data["status"] == "created"
    assert data["deduplicated"] is False


def test_paginated_response():
    p = PaginatedResponse(
        items=[],
        total=50,
        page=2,
        per_page=20,
        pages=3,
    )
    assert p.pages == 3
