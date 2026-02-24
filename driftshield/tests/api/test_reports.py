import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import Base, SessionModel, DecisionNodeModel, ReportModel


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


@pytest.fixture
def seeded_session(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(
        id=session_id, agent_id="test", started_at=datetime.now(timezone.utc), status="completed"
    )
    node = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, sequence_num=1,
        event_type="TOOL_CALL", action="test",
    )
    db_session.add_all([s, node])
    db_session.commit()
    return session_id


def test_generate_report(client, auth_headers, seeded_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["report_type"] == "full"


def test_list_reports_for_session(client, auth_headers, seeded_session, db_session):
    report = ReportModel(
        id=uuid.uuid4(),
        session_id=seeded_session,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Report",
        generated_by="test",
    )
    db_session.add(report)
    db_session.commit()

    response = client.get(f"/api/sessions/{seeded_session}/reports", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_report_by_id(client, auth_headers, seeded_session, db_session):
    report_id = uuid.uuid4()
    report = ReportModel(
        id=report_id,
        session_id=seeded_session,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Test Report",
        content_json={"sections": []},
        generated_by="test",
    )
    db_session.add(report)
    db_session.commit()

    response = client.get(f"/api/reports/{report_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["content_markdown"] == "# Test Report"


def test_get_report_not_found(client, auth_headers):
    response = client.get(f"/api/reports/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


def test_generated_report_has_real_content(client, auth_headers, seeded_session, db_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )
    assert response.status_code == 201
    report_id = response.json()["id"]

    # Fetch the report and check it has real content
    get_response = client.get(f"/api/reports/{report_id}", headers=auth_headers)
    data = get_response.json()
    assert "Forensic Analysis Report" in data["content_markdown"]
    assert data["content_json"]["sections"] is not None
    assert len(data["content_json"]["sections"]) == 5


def test_get_graveyard_summary_not_found(client, auth_headers, monkeypatch):
    monkeypatch.delenv("GRAVEYARD_REPORT_PATH", raising=False)
    response = client.get("/api/graveyard/summary", headers=auth_headers)
    assert response.status_code == 404


def test_get_graveyard_summary_content(client, auth_headers, monkeypatch, tmp_path):
    report_path = Path(tmp_path / "graveyard-report.md")
    report_path.write_text("# Graveyard Summary\n\nSignal quality looks stable.", encoding="utf-8")
    monkeypatch.setenv("GRAVEYARD_REPORT_PATH", str(report_path))

    response = client.get("/api/graveyard/summary", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(report_path)
    assert "# Graveyard Summary" in data["content_markdown"]
