import json
import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.json_export import export_json
from driftshield.reports.models import ReportType


@pytest.fixture
def report_data():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="read_file",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    return ReportBuilder().build(session, result, report_type=ReportType.FULL)


def test_export_json_returns_dict(report_data):
    data = export_json(report_data)
    assert isinstance(data, dict)
    assert "session_id" in data
    assert "sections" in data
    assert len(data["sections"]) == 4


def test_export_json_is_serialisable(report_data):
    data = export_json(report_data)
    serialised = json.dumps(data)
    assert isinstance(serialised, str)
    parsed = json.loads(serialised)
    assert parsed["agent_id"] == "test"


def test_export_json_section_structure(report_data):
    data = export_json(report_data)
    section = data["sections"][0]
    assert "title" in section
    assert "content" in section
    assert "node_table" in section
