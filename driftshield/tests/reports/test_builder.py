import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.models import ReportType


@pytest.fixture
def sample_result():
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
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    return result, session


def test_build_full_report(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.FULL)

    assert report_data.session_id == session.id
    assert report_data.agent_id == "test"
    assert report_data.report_type == ReportType.FULL
    assert len(report_data.sections) == 4
    assert report_data.sections[0].title == "Behavioural Lineage Reconstruction"
    assert report_data.sections[1].title == "Candidate Break Point Assessment"
    assert report_data.sections[2].title == "Risk State Transition Mapping"
    assert report_data.sections[3].title == "Systemic Exposure Assessment"


def test_build_summary_report(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.SUMMARY)

    assert report_data.report_type == ReportType.SUMMARY
    assert len(report_data.sections) == 2


def test_lineage_section_has_node_table(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.FULL)

    lineage = report_data.sections[0]
    assert len(lineage.node_table) == len(result.graph.nodes)
    for row in lineage.node_table:
        assert row.event_type in ["TOOL_CALL", "OUTPUT", "BRANCH", "ASSUMPTION", "CONSTRAINT_CHECK", "HANDOFF"]


def test_break_point_section_uses_candidate_break_point_summary(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.FULL)

    break_point = report_data.candidate_break_point
    assert break_point is not None
    assert report_data.sections[1].content.startswith(break_point.summary)
