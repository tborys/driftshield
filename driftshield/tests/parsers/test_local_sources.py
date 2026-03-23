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
