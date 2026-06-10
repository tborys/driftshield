"""Tests for CLI parser registry."""

from pathlib import Path

import pytest

from driftshield.cli.parsers import ParserNotFoundError, detect_parser, get_parser
from driftshield.parsers.claude_desktop import ClaudeDesktopParser
from driftshield.parsers.codex_cli import CodexCliParser
from driftshield.parsers.codex_desktop import CodexDesktopParser
from driftshield.parsers.crewai import CrewAIParser
from driftshield.parsers.langchain import LangChainParser


class TestGetParser:
    def test_get_claude_code_parser(self):
        parser = get_parser("claude_code")
        assert parser.source_type == "claude_code"

    def test_get_auto_defaults_to_claude_code(self):
        parser = get_parser("auto")
        assert parser.source_type == "claude_code"

    def test_get_openclaw_parser(self):
        parser = get_parser("openclaw")
        assert parser.source_type == "openclaw"

    def test_get_claude_desktop_parser(self):
        parser = get_parser("claude_desktop")
        assert isinstance(parser, ClaudeDesktopParser)

    def test_get_codex_cli_parser(self):
        parser = get_parser("codex_cli")
        assert isinstance(parser, CodexCliParser)

    def test_get_codex_desktop_parser(self):
        parser = get_parser("codex_desktop")
        assert isinstance(parser, CodexDesktopParser)

    def test_get_crewai_parser(self):
        parser = get_parser("crewai")
        assert isinstance(parser, CrewAIParser)

    def test_get_langchain_parser(self):
        parser = get_parser("langchain")
        assert isinstance(parser, LangChainParser)

    def test_unknown_parser_raises(self):
        with pytest.raises(ParserNotFoundError) as exc_info:
            get_parser("unknown")
        assert "unknown" in str(exc_info.value)
        assert "claude_code" in str(exc_info.value)


class TestDetectParser:
    def test_detects_jsonl_as_claude_code(self):
        assert detect_parser(Path("session.jsonl")) == "claude_code"

    def test_detects_claude_projects_path(self, tmp_path):
        path = tmp_path / ".claude" / "projects" / "test" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.touch()

        assert detect_parser(path) == "claude_code"

    def test_detects_openclaw_sessions_path(self, tmp_path):
        path = tmp_path / ".openclaw" / "agents" / "engineering" / "sessions" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.touch()

        assert detect_parser(path) == "openclaw"

    def test_detects_claude_desktop_path(self, tmp_path):
        path = tmp_path / ".claude-desktop" / "sessions" / "session.json"
        path.parent.mkdir(parents=True)
        path.touch()

        assert detect_parser(path) == "claude_desktop"

    def test_detects_codex_cli_path(self, tmp_path):
        path = tmp_path / ".codex" / "sessions" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.touch()

        assert detect_parser(path) == "codex_cli"

    def test_detects_codex_desktop_path(self, tmp_path):
        path = tmp_path / ".codex-desktop" / "sessions" / "session.json"
        path.parent.mkdir(parents=True)
        path.touch()

        assert detect_parser(path) == "codex_desktop"

    def test_unknown_format_returns_none(self):
        assert detect_parser(Path("unknown.xyz")) is None


class TestDetectOpenClawTrajectory:
    _RECORD = (
        '{"type":"session.started","runId":"run-1","traceId":"trace-1",'
        '"schemaVersion":1,"seq":0,"source":"runtime",'
        '"sessionId":"8ad36b0f-9181-4961-9263-770f657db9f5",'
        '"data":{"agentId":"engineering"}}'
    )

    def test_detects_trajectory_suffix(self, tmp_path):
        path = tmp_path / "8ad36b0f.trajectory.jsonl"
        path.touch()

        assert detect_parser(path) == "openclaw_trajectory"

    def test_detects_trajectory_content_in_plain_jsonl(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(self._RECORD + "\n", encoding="utf-8")

        assert detect_parser(path) == "openclaw_trajectory"

    def test_plain_jsonl_without_trajectory_envelope_stays_claude_code(
        self, tmp_path
    ):
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"type":"assistant","sessionId":"s","message":{}}\n', encoding="utf-8"
        )

        assert detect_parser(path) == "claude_code"

    def test_missing_jsonl_file_keeps_claude_code_fallback(self):
        assert detect_parser(Path("does-not-exist.jsonl")) == "claude_code"

    def test_get_parser_resolves_openclaw_trajectory(self):
        parser = get_parser("openclaw_trajectory")
        assert parser.source_type == "openclaw_trajectory"


class TestOpenClawTrajectoryAnalysisSeam:
    def test_signature_summary_builds_from_trajectory_file(self, tmp_path):
        """--include-analysis works end to end on a trajectory: the parser is
        detected, events parse, and the matcher produces a summary object
        (zero matches is a valid outcome for a clean run)."""
        import json as _json

        from driftshield.cli._signature_summary import (
            build_signature_summary_from_session,
        )

        def record(record_type, seq, data):
            return {
                "type": record_type,
                "runId": "run-1",
                "traceId": "trace-1",
                "schemaVersion": 1,
                "seq": seq,
                "source": "runtime",
                "sessionId": "8ad36b0f-9181-4961-9263-770f657db9f5",
                "data": data,
            }

        records = [
            record("session.started", 0, {"agentId": "engineering", "trigger": "cron"}),
            record("prompt.submitted", 1, {"prompt": "run the heartbeat"}),
            record(
                "model.completed",
                2,
                {"timedOut": True, "assistantTexts": []},
            ),
            record("session.ended", 3, {"status": "error"}),
        ]
        path = tmp_path / "run.trajectory.jsonl"
        path.write_text(
            "\n".join(_json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )

        summary = build_signature_summary_from_session(path)

        assert summary is not None
        assert summary.schema_version
        assert isinstance(summary.matches, list)
