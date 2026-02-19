"""Integration tests using real Claude Code transcripts."""

from pathlib import Path

import pytest

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.core.graph.builder import build_graph
from driftshield.core.analysis.inflection import find_inflection_node


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestRealTranscriptEndToEnd:
    """End-to-end tests with real transcripts."""

    def test_can_build_graph_from_real_transcript(self):
        """Parse real transcript and build lineage graph."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        graph = build_graph(events, session_id=events[0].session_id if events else "test")

        assert len(graph.nodes) > 0
        assert graph.root is not None

    def test_graph_has_connected_nodes(self):
        """Graph nodes are connected via parent relationships."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))
        graph = build_graph(events, session_id=events[0].session_id if events else "test")

        # Check path from last node to root exists
        if len(graph.nodes) > 1:
            last_node = graph.nodes[-1]
            path = graph.path_to_root(last_node.id)
            assert len(path) >= 1

    def test_inflection_detection_runs_without_error(self):
        """Inflection detection completes on real transcript."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))
        graph = build_graph(events, session_id=events[0].session_id if events else "test")

        if graph.nodes:
            last_node = graph.nodes[-1]
            # Should not raise - may return None if no risk flags
            result = find_inflection_node(graph, last_node.id)
            # Result can be None (no risk flags in transcript)
            assert result is None or result.has_risk_flags()
