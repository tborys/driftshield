import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    ExplanationPayload,
    RiskClassification,
    Session as DomainSession,
    SessionStatus,
)
from driftshield.db.models import (
    Base,
    DecisionNodeModel,
    SessionModel,
)
from driftshield.db.persistence import IngestProvenance, PersistenceService
from tests.fixtures.lineage import branching_lineage_events


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_analysis_result():
    """Create a minimal AnalysisResult from two events."""
    session_id = uuid.uuid4()
    event1 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="read_file",
        inputs={"path": "/test"},
        outputs={"content": "data"},
    )
    event2 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.OUTPUT,
        agent_id="test-agent",
        action="respond",
        parent_event_id=event1.id,
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event1, event2])
    return result, domain_session


def _build_analysis_result() -> tuple:
    session_id = uuid.uuid4()
    event1 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="read_file",
        inputs={"path": "/test"},
        outputs={"content": "data"},
    )
    event2 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.OUTPUT,
        agent_id="test-agent",
        action="respond",
        parent_event_id=event1.id,
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    return analyze_session([event1, event2]), domain_session


@pytest.fixture
def sample_ingest_payload(sample_analysis_result):
    result, domain_session = sample_analysis_result
    transcript_bytes = b'{"sessionId":"source-session-123"}\n'
    provenance = IngestProvenance(
        transcript_hash=hashlib.sha256(transcript_bytes).hexdigest(),
        source_session_id="source-session-123",
        source_path="fixtures/source-session-123.jsonl",
        parser_version="claude_code@1",
        ingested_at=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )
    return result, domain_session, provenance


def test_save_analysis_result(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions = db_session.query(SessionModel).all()
    assert len(sessions) == 1
    assert sessions[0].agent_id == "test-agent"

    nodes = db_session.query(DecisionNodeModel).all()
    assert len(nodes) == 2
    assert nodes[0].session_id == domain_session.id


def test_load_session(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    loaded = service.load_session(domain_session.id)
    assert loaded is not None
    assert loaded.id == domain_session.id
    assert loaded.agent_id == "test-agent"


def test_load_graph(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    graph = service.load_graph(domain_session.id)
    assert graph is not None
    assert len(graph.nodes) == 2


def test_load_graph_round_trips_branching_lineage_metadata(db_session):
    session_id = uuid.uuid4()
    events = branching_lineage_events(str(session_id))
    result = analyze_session(events)
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )

    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    stored_merge = (
        db_session.query(DecisionNodeModel)
        .filter(DecisionNodeModel.session_id == session_id)
        .order_by(DecisionNodeModel.sequence_num.desc())
        .first()
    )
    assert stored_merge is not None
    assert stored_merge.metadata_json["lineage"]["parent_ids"] == [
        str(events[1].id),
        str(events[2].id),
    ]

    graph = service.load_graph(session_id)
    assert graph is not None
    merge_node = graph.get_node(events[-1].id)
    assert merge_node is not None
    assert merge_node.parent_ids == [events[1].id, events[2].id]
    assert [edge.source_id for edge in graph.incoming_edges(events[-1].id)] == [
        events[1].id,
        events[2].id,
    ]


def test_load_graph_preserves_stored_sequence_order_when_timestamps_disagree(db_session):
    session_id = uuid.uuid4()
    service = PersistenceService(db_session)

    session = SessionModel(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status="completed",
    )
    later_timestamp = datetime(2026, 4, 23, 10, 0, 5, tzinfo=timezone.utc)
    earlier_timestamp = datetime(2026, 4, 23, 10, 0, 1, tzinfo=timezone.utc)

    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    db_session.add(session)
    db_session.add_all(
        [
            DecisionNodeModel(
                id=first_id,
                session_id=session_id,
                sequence_num=0,
                timestamp=later_timestamp,
                event_type="TOOL_CALL",
                action="first",
                parent_node_id=None,
                metadata_json={},
            ),
            DecisionNodeModel(
                id=second_id,
                session_id=session_id,
                sequence_num=1,
                timestamp=earlier_timestamp,
                event_type="OUTPUT",
                action="second",
                parent_node_id=first_id,
                metadata_json={},
            ),
        ]
    )
    db_session.commit()

    graph = service.load_graph(session_id)

    assert graph is not None
    assert [node.id for node in graph.nodes] == [first_id, second_id]
    assert [node.sequence_num for node in graph.nodes] == [0, 1]
    assert graph.incoming_edges(second_id)[0].source_id == first_id


def test_load_nonexistent_session(db_session):
    service = PersistenceService(db_session)
    loaded = service.load_session(uuid.uuid4())
    assert loaded is None


def test_list_sessions(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=20)
    assert total == 1
    assert len(sessions) == 1
    assert sessions[0].id == domain_session.id


def test_list_sessions_pagination(db_session):
    service = PersistenceService(db_session)
    now = datetime.now(timezone.utc)
    for i in range(5):
        s = SessionModel(
            id=uuid.uuid4(), started_at=now, status="completed", agent_id=f"agent-{i}"
        )
        db_session.add(s)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=2)
    assert total == 5
    assert len(sessions) == 2

    sessions, total = service.list_sessions(page=3, per_page=2)
    assert total == 5
    assert len(sessions) == 1


def test_ingest_persists_transcript_provenance(db_session, sample_ingest_payload):
    result, domain_session, provenance = sample_ingest_payload
    service = PersistenceService(db_session)

    outcome = service.ingest(domain_session, result, provenance)
    db_session.commit()

    assert outcome.status == "created"
    assert outcome.deduplicated is False

    stored = db_session.get(SessionModel, domain_session.id)
    assert stored is not None
    assert stored.transcript_hash == provenance.transcript_hash
    assert stored.source_session_id == provenance.source_session_id
    assert stored.source_path == provenance.source_path
    assert stored.parser_version == provenance.parser_version
    assert stored.ingested_at is not None
    assert stored.ingested_at.replace(tzinfo=timezone.utc) == provenance.ingested_at


def test_ingest_is_idempotent_and_returns_explicit_dedupe(db_session, sample_ingest_payload):
    result, domain_session, provenance = sample_ingest_payload
    service = PersistenceService(db_session)

    first = service.ingest(domain_session, result, provenance)
    db_session.commit()

    second = service.ingest(domain_session, result, provenance)
    db_session.commit()

    assert first.status == "created"
    assert second.status == "deduped"
    assert second.deduplicated is True
    assert second.session_id == domain_session.id
    assert second.total_events == first.total_events
    assert second.flagged_events == first.flagged_events
    assert second.has_inflection == first.has_inflection

    sessions = db_session.query(SessionModel).all()
    nodes = db_session.query(DecisionNodeModel).all()
    assert len(sessions) == 1
    assert len(nodes) == len(result.graph.nodes)


def test_ingest_allows_reprocessing_when_parser_version_changes(db_session, sample_ingest_payload):
    result, domain_session, provenance = sample_ingest_payload
    service = PersistenceService(db_session)

    first = service.ingest(domain_session, result, provenance)
    db_session.commit()

    second_result, second_session = _build_analysis_result()
    second_provenance = IngestProvenance(
        transcript_hash=provenance.transcript_hash,
        source_session_id=provenance.source_session_id,
        source_path=provenance.source_path,
        parser_version="claude_code@2",
        ingested_at=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
    )

    second = service.ingest(second_session, second_result, second_provenance)
    db_session.commit()

    assert first.status == "created"
    assert second.status == "created"
    assert second.deduplicated is False
    assert second.session_id == second_session.id

    sessions = db_session.query(SessionModel).order_by(SessionModel.parser_version).all()
    assert len(sessions) == 2
    assert [session.parser_version for session in sessions] == ["claude_code@1", "claude_code@2"]


def test_save_and_load_graph_round_trip_explanations(db_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="review_sections",
        inputs={"sections": ["intro", "body", "appendix"]},
        outputs={"reviewed_sections": ["intro", "body"]},
        risk_classification=RiskClassification(
            coverage_gap=True,
            explanations={
                "coverage_gap": ExplanationPayload(
                    reason="Output referenced fewer items than were provided in the input.",
                    confidence=0.86,
                    evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
                )
            },
        ),
    )
    session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event])

    service = PersistenceService(db_session)
    service.save(session, result)
    db_session.commit()

    saved_node = db_session.query(DecisionNodeModel).filter(DecisionNodeModel.session_id == session_id).one()
    assert saved_node.risk_explanations == {
        "coverage_gap": {
            "reason": "Output referenced fewer items than were provided in the input.",
            "confidence": 0.86,
            "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
        }
    }
    assert saved_node.inflection_explanation == {
        "reason": "Selected as the inflection point using weighted scoring across severity, compounding risk, recovery opportunity, and point-of-no-return behaviour.",
        "confidence": 1.0,
        "evidence_refs": [
            f"node:{event.id}",
            "risk:coverage_gap",
            "inflection_reason:severity from coverage_gap",
            "inflection_reason:proximity to the observed failure",
            "inflection_reason:point-of-no-return position near the observed failure",
        ],
    }

    graph = service.load_graph(session_id)

    assert graph is not None
    assert graph.nodes[0].is_inflection_node is True
    loaded_event = graph.nodes[0].event
    assert loaded_event.risk_classification is not None
    assert loaded_event.risk_classification.explanations["coverage_gap"] == ExplanationPayload(
        reason="Output referenced fewer items than were provided in the input.",
        confidence=0.86,
        evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
    )
    assert loaded_event.metadata["inflection_explanation"] == {
        "reason": "Selected as the inflection point using weighted scoring across severity, compounding risk, recovery opportunity, and point-of-no-return behaviour.",
        "confidence": 1.0,
        "evidence_refs": [
            f"node:{event.id}",
            "risk:coverage_gap",
            "inflection_reason:severity from coverage_gap",
            "inflection_reason:proximity to the observed failure",
            "inflection_reason:point-of-no-return position near the observed failure",
        ],
    }
