"""Tests for the OpenClaw transcript parser."""

from driftshield.core.models import EventType
from driftshield.parsers.openclaw import OpenClawParser


class TestOpenClawParser:
    def test_parses_user_assistant_tool_and_tool_result_flow(self):
        parser = OpenClawParser()
        content = "\n".join(
            [
                '{"type":"session","id":"session-1","timestamp":"2026-03-21T20:00:00Z"}',
                '{"type":"message","id":"u1","parentId":null,"timestamp":"2026-03-21T20:00:01Z","message":{"role":"user","content":[{"type":"text","text":"Please check this repo."}]}}',
                '{"type":"message","id":"a1","parentId":"u1","timestamp":"2026-03-21T20:00:02Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"tool-1","name":"read","arguments":{"file_path":"README.md"}},{"type":"text","text":"I checked it."}]}}',
                '{"type":"message","id":"r1","parentId":"a1","timestamp":"2026-03-21T20:00:03Z","message":{"role":"toolResult","toolCallId":"tool-1","toolName":"read","content":[{"type":"text","text":"# Hello"}],"details":{"status":"completed"},"isError":false}}',
            ]
        )

        events = parser.parse(content)

        assert [event.action for event in events] == [
            "user_message",
            "read",
            "assistant_narrative",
        ]
        assert events[0].event_type == EventType.OUTPUT
        assert events[0].outputs["text"] == "Please check this repo."
        assert events[1].event_type == EventType.TOOL_CALL
        assert events[1].inputs == {"file_path": "README.md"}
        assert events[1].outputs["result"] == "# Hello"
        assert events[2].outputs["text"] == "I checked it."

    def test_marks_sessions_spawn_as_handoff(self):
        parser = OpenClawParser()
        content = "\n".join(
            [
                '{"type":"session","id":"session-2","timestamp":"2026-03-21T20:00:00Z"}',
                '{"type":"message","id":"a1","parentId":null,"timestamp":"2026-03-21T20:00:02Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"tool-2","name":"sessions_spawn","arguments":{"task":"Investigate bug"}}]}}',
            ]
        )

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.HANDOFF
        assert events[0].metadata["semantic_action_category"] == "handoff"

    def test_emits_model_snapshot_as_branch_event(self):
        parser = OpenClawParser()
        content = "\n".join(
            [
                '{"type":"session","id":"session-3","timestamp":"2026-03-21T20:00:00Z"}',
                '{"type":"custom","customType":"model-snapshot","data":{"provider":"openai-codex","modelId":"gpt-5.4"},"id":"c1","parentId":null,"timestamp":"2026-03-21T20:00:01Z"}',
            ]
        )

        events = parser.parse(content)

        assert len(events) == 1
        assert events[0].event_type == EventType.BRANCH
        assert events[0].action == "model_snapshot"
        assert events[0].outputs["modelId"] == "gpt-5.4"
