"""Tests for CLI parser registry."""

from pathlib import Path

import pytest

from driftshield.cli.parsers import ParserNotFoundError, detect_parser, get_parser


class TestGetParser:
    def test_get_claude_code_parser(self):
        """Can get claude_code parser by name."""
        parser = get_parser("claude_code")
        assert parser.source_type == "claude_code"

    def test_get_auto_defaults_to_claude_code(self):
        """Auto parser returns claude_code for now."""
        parser = get_parser("auto")
        assert parser.source_type == "claude_code"

    def test_get_openclaw_parser(self):
        """Can get openclaw parser by name."""
        parser = get_parser("openclaw")
        assert parser.source_type == "openclaw"

    def test_unknown_parser_raises(self):
        """Unknown parser name raises ParserNotFoundError."""
        with pytest.raises(ParserNotFoundError) as exc_info:
            get_parser("unknown")
        assert "unknown" in str(exc_info.value)
        assert "claude_code" in str(exc_info.value)  # Lists available


class TestDetectParser:
    def test_detects_jsonl_as_claude_code(self):
        """JSONL files detected as claude_code."""
        parser_name = detect_parser(Path("session.jsonl"))
        assert parser_name == "claude_code"

    def test_detects_claude_projects_path(self, tmp_path):
        """Files under ~/.claude/projects/ detected as claude_code."""
        claude_path = tmp_path / ".claude" / "projects" / "test" / "session.jsonl"
        claude_path.parent.mkdir(parents=True)
        claude_path.touch()

        parser_name = detect_parser(claude_path)
        assert parser_name == "claude_code"

    def test_detects_openclaw_sessions_path(self, tmp_path):
        """Files under ~/.openclaw/agents/*/sessions/ detected as openclaw."""
        openclaw_path = tmp_path / ".openclaw" / "agents" / "engineering" / "sessions" / "session.jsonl"
        openclaw_path.parent.mkdir(parents=True)
        openclaw_path.touch()

        parser_name = detect_parser(openclaw_path)
        assert parser_name == "openclaw"

    def test_unknown_format_returns_none(self):
        """Unknown format returns None."""
        parser_name = detect_parser(Path("unknown.xyz"))
        assert parser_name is None
