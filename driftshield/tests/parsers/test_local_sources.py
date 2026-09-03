"""Tests for Claude Desktop and Codex transcript parsers."""

from pathlib import Path

from driftshield.core.models import EventType
from driftshield.parsers.claude_desktop import ClaudeDesktopParser
from driftshield.parsers.codex_cli import CodexCliParser
from driftshield.parsers.codex_desktop import CodexDesktopParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


def test_claude_desktop_ingests_representative_session():
    parser = ClaudeDesktopParser()
    events = parser.parse_file(str(FIXTURES_DIR / "sample_claude_desktop_session.json"))

    assert [event.event_type for event in events] == [
        EventType.OUTPUT,
        EventType.TOOL_CALL,
        EventType.OUTPUT,
    ]
    assert events[0].outputs["text"] == "Please inspect the README and summarise the risks."
    assert events[1].action == "Read"
    assert events[1].inputs == {"file_path": "README.md"}
    assert events[1].outputs["result"] == "# DriftShield\n"
    assert events[2].outputs["text"] == "The README is short and has no obvious issues."
    assert all(event.session_id == "claude-desktop-session-1" for event in events)


def test_codex_cli_ingests_representative_session():
    parser = CodexCliParser()
    events = parser.parse_file(str(FIXTURES_DIR / "sample_codex_cli_session.jsonl"))

    assert [event.event_type for event in events] == [
        EventType.OUTPUT,
        EventType.TOOL_CALL,
        EventType.OUTPUT,
    ]
    assert events[0].agent_id == "user"
    assert events[1].action == "shell"
    assert events[1].outputs["result"] == "test-suite ok"
    assert events[2].outputs["text"] == "Tests are green."
    assert all(event.session_id == "codex-cli-session-1" for event in events)


def test_codex_desktop_ingests_representative_session():
    parser = CodexDesktopParser()
    events = parser.parse_file(str(FIXTURES_DIR / "sample_codex_desktop_session.json"))

    assert [event.event_type for event in events] == [
        EventType.OUTPUT,
        EventType.TOOL_CALL,
        EventType.OUTPUT,
    ]
    assert events[1].action == "edit"
    assert events[1].inputs == {"file_path": "app.py", "instruction": "Rename foo to bar"}
    assert events[2].outputs["text"] == "Renamed foo to bar in app.py."
    assert all(event.session_id == "codex-desktop-session-1" for event in events)


def test_codex_cli_parse_method_handles_jsonl_content():
    """parse() routes JSONL content correctly, not just parse_file()."""
    parser = CodexCliParser()
    content = (FIXTURES_DIR / "sample_codex_cli_session.jsonl").read_text()
    events = parser.parse(content)

    assert len(events) == 3
    assert events[0].agent_id == "user"
    assert events[1].action == "shell"
    assert events[2].outputs["text"] == "Tests are green."


# --------------------------------------------------------------------------- #
# Codex rollout envelope (``~/.codex/sessions/<y>/<m>/<d>/rollout-*.jsonl``)
# --------------------------------------------------------------------------- #

ROLLOUT_FIXTURE = FIXTURES_DIR / "sample_codex_cli_rollout.jsonl"
ROLLOUT_SESSION_ID = "019f504c-c3d2-78e3-897e-6896b39453f6"


def _rollout_events():
    return CodexCliParser().parse_file(str(ROLLOUT_FIXTURE))


def test_codex_rollout_yields_events_with_session_id_from_session_meta():
    events = _rollout_events()

    assert len(events) > 0
    assert all(event.session_id == ROLLOUT_SESSION_ID for event in events)


def test_codex_rollout_maps_user_and_assistant_messages():
    events = _rollout_events()

    user_messages = [e for e in events if e.action == "user_message"]
    assert [e.outputs["text"] for e in user_messages] == ["<redacted user prompt>"]
    assert all(e.agent_id == "user" for e in user_messages)
    assert all(e.event_type == EventType.OUTPUT for e in user_messages)

    narratives = [e for e in events if e.action == "assistant_narrative"]
    assert len(narratives) == 4
    assert all(e.outputs["text"] == "<redacted assistant message>" for e in narratives)
    assert all(e.agent_id == "gpt-5.6-sol" for e in narratives)

    # Developer instructions and injected context blocks are not conversation.
    texts = [e.outputs.get("text", "") for e in events]
    assert not any("developer instructions" in t or "environment_context" in t for t in texts)


def test_codex_rollout_maps_tool_calls_with_categories_and_arguments():
    events = _rollout_events()
    tool_calls = [e for e in events if e.event_type == EventType.TOOL_CALL]

    assert [e.action for e in tool_calls] == ["exec"] * 4 + ["wait", "exec", "exec", "wait"]

    exec_call = tool_calls[0]
    assert exec_call.inputs == {"input": "<redacted tool input>"}
    assert exec_call.metadata["semantic_action_category"] == "shell"
    assert exec_call.metadata["tool_use_id"] == "call_TOnlQqyzxsIz9TpTrCbQuEJL"
    assert exec_call.metadata["raw_action"] == "exec"
    assert exec_call.metadata["cwd"] == "/workspace/project"

    wait_call = tool_calls[4]
    assert wait_call.inputs == {"cell_id": "<redacted>", "yield_time_ms": 20000, "max_tokens": 20000}
    assert wait_call.metadata["semantic_action_category"] == "other"
    assert wait_call.metadata["tool_use_id"] == "call_Zmu8ribSpUiEMjUW2LQCYqbW"


def test_codex_rollout_links_tool_results_by_call_id():
    events = _rollout_events()
    tool_calls = [e for e in events if e.event_type == EventType.TOOL_CALL]

    assert tool_calls
    assert all(e.outputs.get("result") for e in tool_calls)
    # Output parts (list) and a bare string output both flatten to text.
    assert tool_calls[0].outputs["result"] == "<redacted tool output>\n<redacted tool output>"
    assert tool_calls[3].outputs["result"] == "<redacted tool output>"
    assert all(e.tool_activity["status"] == "completed" for e in tool_calls)


def test_codex_rollout_marks_turn_boundaries():
    events = _rollout_events()

    assert events[0].action == "turn_started"
    assert events[0].event_type == EventType.BRANCH
    assert events[0].metadata["turn_id"] == "019f504d-04f8-7e33-ba4d-7550523daa1b"
    assert events[-1].action == "turn_completed"
    assert events[-1].event_type == EventType.BRANCH
    assert events[-1].metadata["turn_id"] == "019f504d-04f8-7e33-ba4d-7550523daa1b"


def test_codex_rollout_events_chain_parent_ids():
    events = _rollout_events()

    assert events[0].parent_event_id is None
    for previous, current in zip(events, events[1:]):
        assert current.parent_event_id == previous.id


def _envelope(timestamp: str, record_type: str, payload: dict) -> str:
    import json

    return json.dumps({"timestamp": timestamp, "type": record_type, "payload": payload})


def test_codex_rollout_reasoning_summary_becomes_assistant_narrative():
    content = "\n".join(
        [
            _envelope("2026-07-11T08:30:52.666Z", "session_meta", {"id": "s-1", "timestamp": "2026-07-11T08:30:35Z"}),
            _envelope(
                "2026-07-11T08:30:54.851Z",
                "response_item",
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": "Checking the tests first."}],
                    "encrypted_content": "xyz",
                },
            ),
            _envelope(
                "2026-07-11T08:30:55.000Z",
                "response_item",
                {"type": "reasoning", "id": "rs_2", "summary": [], "encrypted_content": "xyz"},
            ),
            _envelope(
                "2026-07-11T08:30:59.053Z",
                "response_item",
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "name": "apply_patch",
                    "arguments": "{\"patch\":\"*** Begin Patch\"}",
                    "call_id": "call_1",
                },
            ),
            _envelope(
                "2026-07-11T08:31:00.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "id": "fc_2",
                    "name": "spawn_agent",
                    "arguments": "{\"task\":\"review\"}",
                    "call_id": "call_2",
                },
            ),
        ]
    )

    events = CodexCliParser().parse(content)

    assert [e.action for e in events] == ["assistant_narrative", "apply_patch", "spawn_agent"]
    assert events[0].outputs["text"] == "Checking the tests first."
    assert events[0].metadata["raw_action"] == "reasoning_summary"
    assert events[0].session_id == "s-1"
    assert events[1].metadata["semantic_action_category"] == "file_io"
    assert events[1].inputs == {"patch": "*** Begin Patch"}
    assert events[2].event_type == EventType.HANDOFF
    assert events[2].metadata["semantic_action_category"] == "handoff"


def test_codex_rollout_detected_from_content_and_from_path():
    from driftshield.parsers.registry import detect_format

    content = ROLLOUT_FIXTURE.read_text()
    assert detect_format(content) == ("codex_cli", None)

    # Records without session_meta in the sniffed window are still an envelope.
    tail = "\n".join(content.splitlines()[10:20])
    assert detect_format(tail) == ("codex_cli", None)

    # An inconclusive record under the native session store resolves by path.
    line = '{"timestamp":"2026-07-11T08:30:52.666Z","type":"event_msg","payload":{"type":"token_count"}}'
    assert detect_format(line, path_hint="/home/x/.codex/sessions/2026/07/11/rollout-x.jsonl") == (
        "codex_cli",
        None,
    )


def test_codex_legacy_message_lines_still_detected_and_parsed():
    from driftshield.parsers.registry import detect_format

    content = (FIXTURES_DIR / "sample_codex_cli_session.jsonl").read_text()
    assert detect_format(content) == ("codex_cli", None)
    assert len(CodexCliParser().parse(content)) == 3
