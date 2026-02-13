"""Tests for risk classification heuristics."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.analysis.risk import RiskHeuristic, RiskAnalyzer
from driftshield.core.analysis.heuristics import CoverageGapHeuristic


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


class TestRiskAnalyzer:
    def test_analyzer_with_no_heuristics(self):
        """Analyzer with no heuristics returns events unchanged."""
        analyzer = RiskAnalyzer(heuristics=[])
        event = make_event()

        results = analyzer.analyze([event])

        assert len(results) == 1
        assert results[0].risk_classification is None

    def test_analyzer_runs_heuristics(self):
        """Analyzer runs each heuristic on each event."""
        class AlwaysFlagsHeuristic(RiskHeuristic):
            @property
            def name(self) -> str:
                return "always_flags"

            def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
                return RiskClassification(coverage_gap=True)

        analyzer = RiskAnalyzer(heuristics=[AlwaysFlagsHeuristic()])
        event = make_event()

        results = analyzer.analyze([event])

        assert results[0].risk_classification is not None
        assert results[0].risk_classification.coverage_gap is True

    def test_analyzer_merges_multiple_heuristic_results(self):
        """Multiple heuristics can flag different risks on same event."""
        class FlagsCoverageGap(RiskHeuristic):
            @property
            def name(self) -> str:
                return "coverage"

            def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
                return RiskClassification(coverage_gap=True)

        class FlagsContamination(RiskHeuristic):
            @property
            def name(self) -> str:
                return "contamination"

            def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
                return RiskClassification(context_contamination=True)

        analyzer = RiskAnalyzer(heuristics=[FlagsCoverageGap(), FlagsContamination()])
        event = make_event()

        results = analyzer.analyze([event])

        risk = results[0].risk_classification
        assert risk.coverage_gap is True
        assert risk.context_contamination is True

    def test_analyzer_builds_context_from_previous_events(self):
        """Analyzer provides context dict with previous event outputs."""
        captured_context = {}

        class ContextCapture(RiskHeuristic):
            @property
            def name(self) -> str:
                return "capture"

            def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
                captured_context.update(context)
                return None

        event1 = make_event(action="first", outputs={"data": "value1"})
        event2 = make_event(action="second", parent_event_id=event1.id)

        analyzer = RiskAnalyzer(heuristics=[ContextCapture()])
        analyzer.analyze([event1, event2])

        # When analyzing event2, context should include event1's outputs
        assert "previous_outputs" in captured_context
        assert len(captured_context["previous_outputs"]) >= 1


class TestCoverageGapHeuristic:
    """Tests for coverage gap detection."""

    def test_no_flag_when_no_enumerable_inputs(self):
        """No flag when inputs don't contain enumerable items."""
        heuristic = CoverageGapHeuristic()
        event = make_event(
            inputs={"text": "some content"},
            outputs={"summary": "processed"},
        )

        result = heuristic.check(event, {})

        assert result is None

    def test_no_flag_when_all_items_referenced(self):
        """No flag when output references all input items."""
        heuristic = CoverageGapHeuristic()
        event = make_event(
            inputs={"items": ["a", "b", "c"]},
            outputs={"processed_items": ["a", "b", "c"]},
        )

        result = heuristic.check(event, {})

        assert result is None

    def test_flags_when_items_missing_from_output(self):
        """Flags coverage gap when output references fewer items than input."""
        heuristic = CoverageGapHeuristic()
        event = make_event(
            inputs={"subsections": ["a", "b", "c", "d"]},
            outputs={"referenced_subsections": ["a", "b", "d"]},  # Missing c!
        )

        result = heuristic.check(event, {})

        assert result is not None
        assert result.coverage_gap is True

    def test_detects_nested_list_inputs(self):
        """Detects enumerable items in nested input structures."""
        heuristic = CoverageGapHeuristic()
        event = make_event(
            inputs={
                "document": {
                    "sections": ["intro", "body", "conclusion", "appendix"],
                }
            },
            outputs={
                "reviewed_sections": ["intro", "body"],  # Missing 2!
            },
        )

        result = heuristic.check(event, {})

        assert result is not None
        assert result.coverage_gap is True

    def test_ignores_non_matching_key_patterns(self):
        """Only compares keys with matching patterns (e.g., items/processed_items)."""
        heuristic = CoverageGapHeuristic()
        event = make_event(
            inputs={"items": ["a", "b", "c"]},
            outputs={"unrelated_list": ["x", "y"]},  # Different key, no match
        )

        result = heuristic.check(event, {})

        # Should not flag - output key doesn't match input key pattern
        assert result is None

    def test_matches_common_key_patterns(self):
        """Detects common naming patterns for input/output pairs."""
        heuristic = CoverageGapHeuristic()

        # Pattern: X -> referenced_X
        event = make_event(
            inputs={"clauses": ["a", "b", "c"]},
            outputs={"referenced_clauses": ["a", "b"]},
        )
        assert heuristic.check(event, {}) is not None

        # Pattern: X -> processed_X
        event = make_event(
            inputs={"items": ["a", "b", "c"]},
            outputs={"processed_items": ["a"]},
        )
        assert heuristic.check(event, {}) is not None

        # Pattern: X -> reviewed_X
        event = make_event(
            inputs={"sections": ["a", "b", "c"]},
            outputs={"reviewed_sections": ["a", "b"]},
        )
        assert heuristic.check(event, {})
