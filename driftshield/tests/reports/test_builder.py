import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    Session as DomainSession,
    SessionStatus,
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


@pytest.fixture
def failed_report():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    risky_event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=now,
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="review_sections",
        inputs={"sections": ["intro", "body", "appendix"]},
        outputs={"reviewed_sections": ["intro", "body"]},
    )
    failure_event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=now,
        event_type=EventType.OUTPUT,
        agent_id="test-agent",
        action="deliver_answer",
        parent_event_id=risky_event.id,
    )
    result = analyze_session([risky_event, failure_event])
    session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=now,
        status=SessionStatus.FAILED,
    )
    return ReportBuilder().build(session, result, report_type=ReportType.FULL)


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
    assert report_data.sections[3].title == "Single-Run Exposure Assessment"


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


def test_report_v1_contains_summary_findings_and_evidence_index(failed_report):
    assert failed_report.schema_version == "forensic_report.v1"
    assert "observable event" in failed_report.summary.what_happened
    assert "event #" in failed_report.summary.where_it_broke
    assert "single-run evidence" in failed_report.summary.oss_safety_note
    assert "does not claim decision-grade" in failed_report.summary.oss_safety_note

    candidate_findings = [
        finding
        for finding in failed_report.findings
        if finding.finding_kind == "candidate_break_point"
    ]
    assert candidate_findings
    assert all(finding.evidence_refs for finding in failed_report.findings)
    assert any(ref.target_kind == "decision_node" for ref in failed_report.evidence_index)
    assert any(ref.ref_id.startswith("node:") for ref in failed_report.evidence_index)


def test_report_v1_can_describe_local_pattern_resemblance_from_metadata(sample_result):
    result, session = sample_result
    session.metadata = {
        "signature_match": {
            "matches": [
                {
                    "signature_id": "SIG-COMM-001",
                    "family_id": "coverage_gap",
                    "signature_layer": {"symptom": "required evidence skipped"},
                    "confidence": 0.72,
                    "rationale": "local community signature matched reviewed event shape",
                    "evidence_event_refs": [f"node:{result.graph.nodes[0].id}"],
                    "source": "local",
                }
            ]
        }
    }

    report = ReportBuilder().build(session, result, report_type=ReportType.FULL)

    assert report.pattern_matches
    assert report.pattern_matches[0].signature_id == "SIG-COMM-001"
    assert report.pattern_matches[0].family_id == "coverage_gap"
    assert "coverage_gap" in report.summary.pattern_resemblance


def test_report_v1_accepts_legacy_family_only_signature_summary(sample_result):
    result, session = sample_result
    session.metadata = {
        "signature_summary": {
            "status": "matched",
            "primary_family_id": "coverage_gap",
            "matched_family_ids": ["coverage_gap", "verification_failure"],
            "match_count": 2,
            "summary": "Matched two known failure families.",
        }
    }

    report = ReportBuilder().build(session, result, report_type=ReportType.FULL)

    assert [match.family_id for match in report.pattern_matches] == [
        "coverage_gap",
        "verification_failure",
    ]
    assert report.pattern_matches[0].signature_id == "family:coverage_gap"
    assert report.pattern_matches[0].rationale == "Matched two known failure families."
    assert "coverage_gap" in report.summary.pattern_resemblance
    assert "verification_failure" in report.summary.pattern_resemblance


def test_report_v1_ignores_signature_only_payload_without_family_fields(sample_result):
    result, session = sample_result
    session.metadata = {
        "signature_summary": {
            "signature_id": "sig:test",
            "summary": "Incomplete signature payload without family metadata.",
        }
    }

    report = ReportBuilder().build(session, result, report_type=ReportType.FULL)

    assert report.pattern_matches == []
    assert report.summary.pattern_resemblance == (
        "No local pattern resemblance was available from OSS-safe signals."
    )
