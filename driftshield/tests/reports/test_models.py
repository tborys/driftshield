import uuid
from datetime import datetime, timezone

from driftshield.reports.models import (
    ReportData, ReportSection, NodeRow, RiskTransition, ReportType,
)


def test_create_report_data():
    report = ReportData(
        session_id=uuid.uuid4(),
        agent_id="test-agent",
        generated_at=datetime.now(timezone.utc),
        report_type=ReportType.FULL,
        sections=[],
    )
    assert report.report_type == ReportType.FULL
    assert report.sections == []


def test_report_section():
    section = ReportSection(
        title="Behavioural Lineage Reconstruction",
        content="Analysis of decision flow.",
        node_table=[
            NodeRow(
                sequence=1,
                node_id=uuid.uuid4(),
                event_type="TOOL_CALL",
                action="read_file",
                risk_flags=["coverage_gap"],
                is_inflection=False,
            ),
        ],
    )
    assert len(section.node_table) == 1
    assert section.node_table[0].risk_flags == ["coverage_gap"]


def test_risk_transition():
    t = RiskTransition(
        from_node_id=uuid.uuid4(),
        to_node_id=uuid.uuid4(),
        risk_type="coverage_gap",
        description="Gap introduced at read_file, propagated to respond",
    )
    assert t.risk_type == "coverage_gap"


def test_report_type_enum():
    assert ReportType.FULL.value == "full"
    assert ReportType.SUMMARY.value == "summary"
