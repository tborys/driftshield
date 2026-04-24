import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.markdown import render_markdown
from driftshield.reports.models import ReportType


@pytest.fixture
def full_report_data():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="read_file",
            inputs={"items": ["a", "b", "c"]},
            outputs={"summary": "Covers a and b"},
        ),
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.OUTPUT, agent_id="test", action="respond",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test-agent", started_at=now, status=SessionStatus.COMPLETED,
    )
    builder = ReportBuilder()
    return builder.build(session, result, report_type=ReportType.FULL)


def test_render_full_report_markdown(full_report_data):
    md = render_markdown(full_report_data)
    assert "# Forensic Analysis Report" in md
    assert "test-agent" in md
    assert "Behavioural Lineage Reconstruction" in md
    assert "Candidate Break Point Assessment" in md
    assert "Risk State Transition Mapping" in md
    assert "Single-Run Exposure Assessment" in md
    assert "What happened" in md
    assert "Confidence and uncertainty" in md
    assert "Evidence Index" in md
    assert "does not claim decision-grade" in md


def test_render_has_node_table(full_report_data):
    md = render_markdown(full_report_data)
    assert "TOOL_CALL" in md
    assert "read_file" in md


def test_render_summary_report():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="start",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    builder = ReportBuilder()
    data = builder.build(session, result, report_type=ReportType.SUMMARY)
    md = render_markdown(data)
    assert "# Forensic Analysis Report" in md
    assert "Behavioural Lineage Reconstruction" in md
    # Summary should NOT have the full report-only sections.
    assert "Risk State Transition Mapping" not in md
