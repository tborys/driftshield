"""Tests for session analysis orchestration."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from driftshield.core.analysis.session import analyze_session, AnalysisResult
from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.parsers.claude_code import ClaudeCodeParser
from tests.fixtures.scenarios import (
    coverage_gap_scenario,
    cross_tool_contamination_scenario,
)


FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "transcripts"


def make_event(**kwargs) -> CanonicalEvent:
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestAnalyzeSession:
    """Tests for analyze_session function."""

    def test_returns_analysis_result(self):
        """analyze_session returns AnalysisResult with graph and events."""
        graph, _ = coverage_gap_scenario()

        # Extract events from graph nodes
        events = [node.event for node in graph.nodes]

        result = analyze_session(events)

        assert isinstance(result, AnalysisResult)
        assert result.graph is not None
        assert len(result.events) > 0

    def test_detects_coverage_gap_in_scenario(self):
        """Detects coverage gap in synthetic scenario."""
        graph, metadata = coverage_gap_scenario()

        # Get events without pre-set risk flags (simulate fresh parse)
        events = [node.event for node in graph.nodes]
        for e in events:
            e.risk_classification = None

        result = analyze_session(events)

        # Should detect the coverage gap
        flagged = [e for e in result.events if e.has_risk_flags()]
        assert len(flagged) > 0

        # Check coverage_gap flag is set on at least one event
        coverage_gaps = [
            e for e in result.events
            if e.risk_classification and e.risk_classification.coverage_gap
        ]
        assert len(coverage_gaps) > 0

    def test_detects_contamination_in_scenario(self):
        """Detects context contamination in synthetic scenario."""
        graph, metadata = cross_tool_contamination_scenario()

        # Get events without pre-set risk flags
        events = [node.event for node in graph.nodes]
        for e in events:
            e.risk_classification = None

        result = analyze_session(events)

        # Should detect the contamination
        contamination = [
            e for e in result.events
            if e.risk_classification and e.risk_classification.context_contamination
        ]
        assert len(contamination) > 0

    def test_finds_inflection_node(self):
        """analyze_session finds inflection node when risks detected."""
        graph, metadata = coverage_gap_scenario()

        events = [node.event for node in graph.nodes]
        for e in events:
            e.risk_classification = None

        result = analyze_session(events)

        # If risks were detected, inflection should be found
        if any(e.has_risk_flags() for e in result.events):
            assert result.inflection_node is not None

    def test_preserves_legacy_inflection_node_when_candidate_break_point_is_uncertain(self):
        event1 = make_event(
            action="early_policy_drift",
            risk_classification=RiskClassification(policy_divergence=True),
        )
        event2 = make_event(
            action="later_constraint_drift",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(constraint_violation=True),
        )
        event3 = make_event(action="failure", parent_event_id=event2.id)

        result = analyze_session([event1, event2, event3])

        assert result.candidate_break_point is not None
        assert result.candidate_break_point.status.value == "no_clear_break_point"
        assert result.inflection_node is not None
        assert result.inflection_explanation is not None

    def test_with_real_transcript(self):
        """Runs analysis on real transcript without error."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        result = analyze_session(events)

        assert result.graph is not None
        assert len(result.events) > 0
        # Inflection may be None if no risks detected (expected for clean session)

    def test_detects_assumption_mutation_in_dogfood_session(self):
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "dogfood" / "assumption_mutation_session.jsonl"))

        result = analyze_session(events)

        assert result.risk_summary["assumption_mutation"] == 1
        flagged_event = result.events[-1]
        assert flagged_event.risk_classification is not None
        assert flagged_event.risk_classification.assumption_mutation is True

    def test_does_not_flag_assumption_mutation_for_clean_or_multi_flag_regressions(self):
        parser = ClaudeCodeParser()

        clean_events = parser.parse_file(str(FIXTURES_DIR / "dogfood" / "clean_session.jsonl"))
        clean_result = analyze_session(clean_events)
        assert clean_result.risk_summary["assumption_mutation"] == 0

        multi_flag_events = parser.parse_file(str(FIXTURES_DIR / "dogfood" / "multi_flag_session.jsonl"))
        multi_flag_result = analyze_session(multi_flag_events)
        assert multi_flag_result.risk_summary["assumption_mutation"] == 0

    def test_detects_policy_divergence_in_dogfood_session(self):
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "dogfood" / "policy_divergence_session.jsonl"))

        result = analyze_session(events)

        assert result.risk_summary["policy_divergence"] == 1
        flagged_event = result.events[-1]
        assert flagged_event.risk_classification is not None
        assert flagged_event.risk_classification.policy_divergence is True

    def test_detects_constraint_violation_in_dogfood_session(self):
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "dogfood" / "constraint_violation_session.jsonl"))

        result = analyze_session(events)

        assert result.risk_summary["constraint_violation"] == 1
        flagged_event = result.events[-1]
        assert flagged_event.risk_classification is not None
        assert flagged_event.risk_classification.constraint_violation is True

    def test_does_not_flag_constraint_violation_after_explicit_user_confirmation(self):
        transcript = "\n".join(
            [
                '{"sessionId":"constraint-confirmed","type":"assistant","timestamp":"2026-03-01T11:00:00Z","message":{"model":"claude","content":[{"type":"text","text":"Please ask for confirmation before destructive actions."}]}}',
                '{"sessionId":"constraint-confirmed","type":"user","timestamp":"2026-03-01T11:00:01Z","message":{"role":"user","content":"Yes, delete the build directory."}}',
                '{"sessionId":"constraint-confirmed","type":"assistant","timestamp":"2026-03-01T11:00:02Z","message":{"model":"claude","content":[{"type":"tool_use","id":"tool_confirmed_delete","name":"bash","input":{"command":"rm -rf build/"}}]}}',
            ]
        )

        events = ClaudeCodeParser().parse(transcript)
        result = analyze_session(events)

        assert result.risk_summary["constraint_violation"] == 0


class TestAnalysisResult:
    """Tests for AnalysisResult structure."""

    def test_has_summary_stats(self):
        """AnalysisResult includes summary statistics."""
        graph, _ = coverage_gap_scenario()
        events = [node.event for node in graph.nodes]

        result = analyze_session(events)

        assert hasattr(result, "total_events")
        assert hasattr(result, "flagged_events")
        assert result.total_events == len(events)
