"""Tests for CLI output formatters."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.analysis.session import AnalysisResult
from driftshield.cli.output import format_summary, format_json


def make_analysis_result(
    events: list[CanonicalEvent] | None = None,
    flagged: int = 0,
    inflection_action: str | None = None,
) -> AnalysisResult:
    """Create test AnalysisResult."""
    if events is None:
        events = []

    session_id = "test-session"
    graph = build_graph(events, session_id=session_id)

    inflection_node = None
    if inflection_action and graph.nodes:
        for node in graph.nodes:
            if node.action == inflection_action:
                inflection_node = node
                break

    return AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=inflection_node,
        total_events=len(events),
        flagged_events=flagged,
    )


class TestFormatSummary:
    def test_empty_session(self):
        """Empty session shows zero events."""
        result = make_analysis_result()
        output = format_summary(result)

        assert "Events:  0" in output or "Events: 0" in output
        assert "Flagged: 0" in output or "Flagged:  0" in output

    def test_shows_session_id(self):
        """Summary shows session ID."""
        result = make_analysis_result()
        output = format_summary(result)

        assert "test-session" in output

    def test_shows_risk_counts(self):
        """Summary shows risk type counts when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="risky_action",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        result = AnalysisResult(
            events=[event],
            graph=build_graph([event], session_id="test-session"),
            inflection_node=None,
            total_events=1,
            flagged_events=1,
        )
        output = format_summary(result)

        assert "coverage_gap" in output

    def test_shows_inflection_point(self):
        """Summary shows inflection point when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="bad_decision",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        graph = build_graph([event], session_id="test-session")
        result = AnalysisResult(
            events=[event],
            graph=graph,
            inflection_node=graph.nodes[0],
            total_events=1,
            flagged_events=1,
        )
        output = format_summary(result)

        assert "Inflection" in output
        assert "bad_decision" in output


class TestFormatJson:
    def test_returns_valid_json_structure(self):
        """JSON output has expected structure."""
        result = make_analysis_result()
        output = format_json(result)

        assert "session_id" in output
        assert "total_events" in output
        assert "flagged_events" in output
        assert "risks" in output

    def test_includes_inflection_when_present(self):
        """JSON includes inflection data when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="inflection_action",
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        graph = build_graph([event], session_id="test-session")
        result = AnalysisResult(
            events=[event],
            graph=graph,
            inflection_node=graph.nodes[0],
            total_events=1,
            flagged_events=1,
        )
        output = format_json(result)

        assert "inflection" in output
        assert "inflection_action" in output
