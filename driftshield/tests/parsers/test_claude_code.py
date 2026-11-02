"""Tests for Claude Code transcript parser."""

from pathlib import Path

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

    def test_parses_assistant_narrative_into_output_events(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s1","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"text","text":"I will inspect this first."}]}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.OUTPUT
        assert events[0].action == "assistant_narrative"
        assert events[0].outputs.get("text") == "I will inspect this first."

    def test_parses_plain_user_messages_into_user_events(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s1","type":"user","timestamp":"2026-03-01T10:00:00Z","message":{"role":"user","content":"Please delete the build directory."}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.OUTPUT
        assert events[0].agent_id == "user"
        assert events[0].action == "user_message"
        assert events[0].outputs.get("text") == "Please delete the build directory."

    def test_detects_handoff_events_from_task_spawn(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s2","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"tool_use","id":"t1","name":"Task","input":{"description":"delegate"}}]}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.HANDOFF
        assert events[0].metadata.get("raw_action") == "Task"

    def test_does_not_treat_spawned_as_narrative_handoff(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s2b","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"text","text":"I spawned a new test file and will inspect it next."}]}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.OUTPUT
        assert events[0].action == "assistant_narrative"

    def test_captures_hook_progress_events(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s3","type":"progress","timestamp":"2026-03-01T10:00:00Z","data":{"type":"hook_progress","hookEvent":"SessionStart","hookName":"SessionStart:startup","command":"hooks/start.sh"},"toolUseID":"x1"}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.BRANCH
        assert events[0].action == "hook_progress"
        assert events[0].metadata.get("hook_event") == "SessionStart"

    def test_adds_semantic_action_category_to_tool_calls(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s4","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":"/tmp/a"}}]}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].metadata.get("semantic_action_category") == "file_io"

    def test_tool_result_without_tool_use_id_does_not_break_parser(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s5","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/a"}}]}}',
            '{"sessionId":"s5","type":"user","timestamp":"2026-03-01T10:00:01Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"missing","content":"ok","is_error":false}]}}',
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].outputs == {}

    def test_non_object_tool_inputs_do_not_break_normalization(self):
        parser = ClaudeCodeParser()
        content = "\n".join([
            '{"sessionId":"s6","type":"assistant","timestamp":"2026-03-01T10:00:00Z","message":{"model":"claude","content":[{"type":"tool_use","id":"t6","name":"bash","input":["npm","test"]}]}}'
        ])

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].inputs == ["npm", "test"]
        assert events[0].tool_activity == {
            "name": "bash",
            "category": "shell",
            "raw_name": "bash",
            "status": "pending",
            "input_keys": [],
            "has_outputs": False,
        }


def _record(kind: str, message: object, **extra: object) -> str:
    import json

    return json.dumps({"type": kind, "sessionId": "synthetic-s1",
                       "timestamp": "2026-01-01T00:00:00Z", "message": message, **extra})


def _valid_lines() -> list[str]:
    return [
        _record("user", {"role": "user", "content": "please list the files"}),
        _record("assistant", {"role": "assistant", "model": "m", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
        ]}),
        _record("assistant", {"role": "assistant", "model": "m", "content": [
            {"type": "text", "text": "done listing"},
        ]}),
    ]


def _shape(events):
    return [(e.event_type, e.action, e.inputs, e.outputs, e.agent_id) for e in events]


def test_non_object_lines_are_skipped():
    valid = _valid_lines()
    clean = ClaudeCodeParser().parse("\n".join(valid))
    odd = [valid[0], "[1, 2]", valid[1], '"just a string"', valid[2], "42"]
    events = ClaudeCodeParser().parse("\n".join(odd))
    assert len(clean) == 3
    assert _shape(events) == _shape(clean)


def test_non_object_message_is_skipped():
    valid = _valid_lines()
    clean = ClaudeCodeParser().parse("\n".join(valid))
    bad = [
        _record(kind, msg)
        for kind in ("assistant", "user")
        for msg in (None, [1], "text", 7)
    ]
    events = ClaudeCodeParser().parse("\n".join(bad[:4] + valid + bad[4:]))
    assert _shape(events) == _shape(clean)


def test_assistant_content_not_a_list_is_skipped():
    valid = _valid_lines()
    clean = ClaudeCodeParser().parse("\n".join(valid))
    bad = [
        _record("assistant", {"role": "assistant", "content": 5}),
        _record("assistant", {"role": "assistant", "content": None}),
    ]
    events = ClaudeCodeParser().parse("\n".join(bad + valid))
    assert _shape(events) == _shape(clean)
