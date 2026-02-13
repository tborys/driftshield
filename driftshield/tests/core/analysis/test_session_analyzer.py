"""Tests for session analysis orchestration."""

from pathlib import Path

import pytest

from driftshield.core.analysis.session import analyze_session, AnalysisResult
from driftshield.parsers.claude_code import ClaudeCodeParser
from tests.fixtures.scenarios import (
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
)


FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "transcripts"


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

    def test_with_real_transcript(self):
        """Runs analysis on real transcript without error."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        result = analyze_session(events)

        assert result.graph is not None
        assert len(result.events) > 0
        # Inflection may be None if no risks detected (expected for clean session)


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
