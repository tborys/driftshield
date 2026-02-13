"""Tests for Claude Code transcript parser."""

from pathlib import Path

import pytest

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.core.models import EventType


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestClaudeCodeParser:
    def test_parse_file_returns_events(self):
        """Parser extracts events from JSONL file."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        assert len(events) > 0
        assert all(e.session_id for e in events)

    def test_extracts_tool_calls(self):
        """Parser extracts tool_use entries as TOOL_CALL events."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        tool_calls = [e for e in events if e.event_type == EventType.TOOL_CALL]
        assert len(tool_calls) > 0

    def test_tool_call_has_action_and_inputs(self):
        """Tool call events have action (tool name) and inputs."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        tool_calls = [e for e in events if e.event_type == EventType.TOOL_CALL]
        for tc in tool_calls[:5]:  # Check first 5
            assert tc.action  # Tool name
            assert isinstance(tc.inputs, dict)

    def test_events_have_timestamps(self):
        """All events have valid timestamps."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        for event in events:
            assert event.timestamp is not None

    def test_events_linked_by_parent(self):
        """Events are linked via parent_event_id."""
        parser = ClaudeCodeParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_code_session.jsonl"))

        # At least some events should have parents (not root)
        events_with_parents = [e for e in events if e.parent_event_id is not None]
        assert len(events_with_parents) > 0

    def test_source_type(self):
        """Parser identifies as claude_code."""
        parser = ClaudeCodeParser()
        assert parser.source_type == "claude_code"
