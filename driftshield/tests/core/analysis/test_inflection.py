"""Tests for inflection node detection."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.analysis.inflection import find_inflection_node, select_inflection_node
from tests.fixtures.scenarios import (
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
)


def make_event(**kwargs) -> CanonicalEvent:
    """Factory for creating test events."""
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


class TestFindInflectionNode:
    def test_returns_none_for_empty_graph(self):
        """Empty graph has no inflection node."""
        graph = build_graph([], session_id="test")
        result = find_inflection_node(graph, uuid4())
        assert result is None

    def test_returns_none_for_nonexistent_failure_node(self):
        """Nonexistent failure node returns None."""
        event = make_event()
        graph = build_graph([event], session_id="test")
        result = find_inflection_node(graph, uuid4())
        assert result is None

    def test_returns_none_when_no_risk_flags(self):
        """Graph with no risk flags has no inflection."""
        event1 = make_event(action="first")
        event2 = make_event(action="second", parent_event_id=event1.id)

        graph = build_graph([event1, event2], session_id="test")
        result = find_inflection_node(graph, event2.id)

        assert result is None

    def test_finds_single_risky_node(self):
        """Single node with risk flags is the inflection."""
        event1 = make_event(action="clean")
        event2 = make_event(
            action="risky",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        event3 = make_event(action="failure", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="test")
        result = find_inflection_node(graph, event3.id)

        assert result is not None
        assert result.action == "risky"

    def test_finds_first_risky_node_walking_backward(self):
        """When multiple risky nodes, finds first (closest to failure)."""
        event1 = make_event(
            action="early_risk",
            risk_classification=RiskClassification(policy_divergence=True),
        )
        event2 = make_event(
            action="later_risk",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        event3 = make_event(action="failure", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="test")
        result = find_inflection_node(graph, event3.id)

        # Walking backward from failure, we hit later_risk first
        assert result.action == "later_risk"

    def test_failure_node_itself_can_be_inflection(self):
        """If failure node has risk flags, it is the inflection."""
        event1 = make_event(action="clean")
        event2 = make_event(
            action="failure_with_risk",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(coverage_gap=True),
        )

        graph = build_graph([event1, event2], session_id="test")
        result = find_inflection_node(graph, event2.id)

        assert result.action == "failure_with_risk"

    def test_weighted_scoring_prefers_more_meaningful_earlier_divergence(self):
        """Weighted scoring can beat simple walkback when earlier risk compounds."""
        event1 = make_event(
            action="seed_wrong_assumption",
            risk_classification=RiskClassification(policy_divergence=True),
        )
        event2 = make_event(
            action="compound_bad_state_once",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        event3 = make_event(
            action="compound_bad_state_twice",
            parent_event_id=event2.id,
            risk_classification=RiskClassification(coverage_gap=True),
        )
        event4 = make_event(
            action="failure",
            parent_event_id=event3.id,
        )

        graph = build_graph([event1, event2, event3, event4], session_id="test")

        result = find_inflection_node(graph, event4.id)
        selection = select_inflection_node(graph, event4.id)

        assert result is not None
        assert result.action == "seed_wrong_assumption"
        assert selection.explanation is not None
        assert selection.strategy == "weighted"
        assert selection.explanation.confidence == 0.68
        assert "weighted scoring" in selection.explanation.reason
        assert any(ref.startswith("inflection_reason:") for ref in selection.explanation.evidence_refs)


class TestInflectionWithScenarios:
    """Test inflection detection with synthetic scenarios."""

    def test_coverage_gap_scenario(self):
        """Finds correct inflection in coverage gap scenario."""
        graph, metadata = coverage_gap_scenario()

        # Find the last node (output) as failure point
        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]
        assert result.action == metadata["expected_inflection_node_action"]

    def test_candidate_break_point_returns_no_clear_when_candidates_are_too_close(self):
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

        graph = build_graph([event1, event2, event3], session_id="test")
        selection = select_inflection_node(graph, event3.id)

        assert selection.node is not None
        assert selection.candidate_break_point.status.value == "no_clear_break_point"
        assert selection.candidate_break_point.node_id is None
        assert selection.candidate_break_point.confidence is not None
        assert selection.candidate_break_point.confidence < 0.6
        assert selection.candidate_break_point.uncertainty_reasons

    def test_assumption_introduction_scenario(self):
        """Finds correct inflection in assumption introduction scenario."""
        graph, metadata = assumption_introduction_scenario()

        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]

    def test_cross_tool_contamination_scenario(self):
        """Finds correct inflection in cross-tool contamination scenario."""
        graph, metadata = cross_tool_contamination_scenario()

        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]
