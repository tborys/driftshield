import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import AnalystValidationModel, Base, SessionModel


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with DBSession(engine) as session:
        yield session


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    app = create_app()
    from driftshield.api.dependencies import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-key"}


def _make_session(
    *,
    trust_band: str,
    final_learning_weight: float,
    structural_score: float,
    semantic_score: float,
    source_factor: float,
    reason_codes: list[str],
    requires_review: bool,
    evaluated_at: datetime,
    ingested_at: datetime,
    source_session_id: str | None = "source-session",
    source_path: str | None = "uploads/session.jsonl",
) -> SessionModel:
    session_id = uuid.uuid4()
    return SessionModel(
        id=session_id,
        agent_id="test-agent",
        started_at=ingested_at - timedelta(minutes=1),
        status="completed",
        source_session_id=source_session_id,
        source_path=source_path,
        parser_version="claude_code@1",
        transcript_hash=f"hash-{session_id}",
        ingested_at=ingested_at,
        metadata_json={
            "integrity_summary": {
                "integrity_schema_version": "phase3e.v1",
                "trust_band": trust_band,
                "structural_score": structural_score,
                "semantic_score": semantic_score,
                "source_factor": source_factor,
                "pattern_integrity_score": 0.95,
                "final_learning_weight": final_learning_weight,
                "integrity_reasons": reason_codes,
                "requires_review": requires_review,
                "integrity_evaluated_at": evaluated_at.isoformat(),
                "integrity_policy_version": "phase3e.v1.default",
                "evidence_counts": {"total_events": 3, "flagged_events": 1},
                "pattern_integrity_note": "OSS v1 uses a conservative placeholder because private Pattern Object promotion and recurrence logic are out of scope.",
            },
            "integrity_provenance": {
                "source_type": "claude_code",
                "source_session_id": source_session_id,
                "source_path": source_path,
                "parser_version": "claude_code@1",
                "transcript_hash": f"hash-{session_id}",
                "ingested_at": ingested_at.isoformat(),
                "integrity_policy_version": "phase3e.v1.default",
                "integrity_schema_version": "phase3e.v1",
                "integrity_evaluated_at": evaluated_at.isoformat(),
                "evidence_counts": {"total_events": 3, "flagged_events": 1},
            },
        },
    )


def test_get_integrity_dashboard_metrics(client, auth_headers, db_session):
    now = datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc)
    trusted = _make_session(
        trust_band="trusted",
        final_learning_weight=0.9,
        structural_score=1.0,
        semantic_score=0.9,
        source_factor=1.0,
        reason_codes=["pattern_integrity_placeholder_oss_v1"],
        requires_review=False,
        evaluated_at=now - timedelta(minutes=10),
        ingested_at=now - timedelta(minutes=12),
    )
    provisional = _make_session(
        trust_band="provisional",
        final_learning_weight=0.55,
        structural_score=0.8,
        semantic_score=0.7,
        source_factor=0.85,
        reason_codes=["missing_source_locator"],
        requires_review=True,
        evaluated_at=now - timedelta(minutes=20),
        ingested_at=now - timedelta(minutes=30),
    )
    quarantined = _make_session(
        trust_band="quarantined",
        final_learning_weight=0.2,
        structural_score=0.4,
        semantic_score=0.6,
        source_factor=0.5,
        reason_codes=["missing_parser_version", "missing_source_locator"],
        requires_review=True,
        evaluated_at=now - timedelta(minutes=40),
        ingested_at=now - timedelta(minutes=60),
    )
    db_session.add_all([trusted, provisional, quarantined])
    db_session.flush()
    db_session.add(
        AnalystValidationModel(
            id=uuid.uuid4(),
            session_id=quarantined.id,
            target_type="forensic_feedback",
            target_ref="classification",
            verdict="needs_review",
            confidence=0.8,
            reviewer="tester",
            notes="Queued",
            metadata_json={"forensic_feedback": {"report_id": None}},
            shareable=False,
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.commit()

    response = client.get("/api/dashboard/integrity", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()

    intake = data["integrity_intake_summary"]
    assert intake["status"] == "live"
    assert intake["time_window"] == "all_time"
    assert intake["metrics"]["total_runs_ingested"] == 3
    assert intake["metrics"]["trusted_count"] == 1
    assert intake["metrics"]["provisional_count"] == 1
    assert intake["metrics"]["quarantined_count"] == 1
    assert intake["metrics"]["latest_freshness_timestamp"] == trusted.metadata_json["integrity_summary"]["integrity_evaluated_at"]
    assert intake["metrics"]["final_learning_weight_percentiles"] == {"p10": 0.2, "p50": 0.55, "p90": 0.9}

    breakdown = data["learning_weight_breakdown"]
    assert breakdown["status"] == "live"
    assert breakdown["metrics"]["average_pattern_integrity_score"] == pytest.approx(0.95)
    assert breakdown["metrics"]["top_downgrade_reasons"][0] == {"reason": "missing_source_locator", "count": 2}
    assert sum(bucket["count"] for bucket in breakdown["metrics"]["final_learning_weight_buckets"]) == 3

    quarantine = data["quarantine_review_summary"]
    assert quarantine["status"] == "live"
    assert quarantine["metrics"]["quarantined_count"] == 1
    assert quarantine["metrics"]["requires_review_count"] == 2
    assert quarantine["metrics"]["reviewed_count"] == 1
    assert quarantine["metrics"]["unreviewed_count"] == 0

    freshness = data["integrity_freshness_summary"]
    assert freshness["status"] == "live"
    assert freshness["metrics"]["stale_data"] is False
    assert freshness["metrics"]["latest_freshness_timestamp"] == trusted.metadata_json["integrity_summary"]["integrity_evaluated_at"]
    assert freshness["metrics"]["average_ingestion_to_integrity_latency_seconds"] == pytest.approx((2 * 60 + 10 * 60 + 20 * 60) / 3)

    source_summary = data["source_integrity_summary"]
    assert source_summary["status"] == "live"
    assert source_summary["metrics"]["runs_with_source_locator"] == 3

    assert data["recurrence_quality_summary"]["status"] == "gated"
    assert data["pattern_promotion_summary"]["status"] == "gated"
    assert data["threshold_calibration_summary"]["status"] == "directional"


def test_dashboard_gated_payloads_are_explicit_when_source_granularity_is_missing(client, auth_headers, db_session):
    now = datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        _make_session(
            trust_band="trusted",
            final_learning_weight=0.88,
            structural_score=0.95,
            semantic_score=0.9,
            source_factor=0.95,
            reason_codes=["pattern_integrity_placeholder_oss_v1"],
            requires_review=False,
            evaluated_at=now,
            ingested_at=now - timedelta(minutes=5),
            source_session_id=None,
            source_path=None,
        )
    )
    db_session.commit()

    response = client.get("/api/dashboard/integrity", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["source_integrity_summary"]["status"] == "gated"
    assert data["source_integrity_summary"]["blocked_by"] == ["source_session_id", "source_path"]
    assert data["recurrence_quality_summary"]["blocked_by"]
    assert data["pattern_promotion_summary"]["blocked_by"]


def test_dashboard_uses_persisted_integrity_fields_without_recomputing(client, auth_headers, db_session):
    now = datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc)
    session = _make_session(
        trust_band="trusted",
        final_learning_weight=0.77,
        structural_score=0.11,
        semantic_score=0.22,
        source_factor=0.33,
        reason_codes=["manual_override_for_test"],
        requires_review=False,
        evaluated_at=now,
        ingested_at=now - timedelta(minutes=5),
    )
    db_session.add(session)
    db_session.commit()

    response = client.get("/api/dashboard/integrity", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["integrity_intake_summary"]["metrics"]["trusted_count"] == 1
    assert data["integrity_intake_summary"]["metrics"]["final_learning_weight_percentiles"]["p50"] == 0.77
    assert data["learning_weight_breakdown"]["metrics"]["average_structural_score"] == 0.11
    assert data["learning_weight_breakdown"]["metrics"]["top_downgrade_reasons"] == [
        {"reason": "manual_override_for_test", "count": 1}
    ]


def test_dashboard_marks_stale_data_when_freshness_exceeds_threshold(client, auth_headers, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        _make_session(
            trust_band="quarantined",
            final_learning_weight=0.1,
            structural_score=0.2,
            semantic_score=0.3,
            source_factor=0.4,
            reason_codes=["missing_parser_version"],
            requires_review=True,
            evaluated_at=now - timedelta(days=3),
            ingested_at=now - timedelta(days=3, minutes=15),
        )
    )
    db_session.commit()

    response = client.get("/api/dashboard/integrity", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["integrity_freshness_summary"]["metrics"]["stale_data"] is True
    assert data["integrity_freshness_summary"]["metrics"]["stale_threshold_hours"] == 24
