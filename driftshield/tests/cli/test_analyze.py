"""Tests for analyze command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestAnalyzeCommand:
    def test_analyze_single_file(self):
        """Can analyze a single JSONL file."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl")],
        )

        assert result.exit_code == 0
        assert "DriftShield Analysis" in result.output
        assert "Events:" in result.output

    def test_analyze_with_verbose(self):
        """Verbose flag shows event table."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl"), "--verbose"],
        )

        assert result.exit_code == 0
        assert "Action" in result.output  # Table header

    def test_analyze_with_json(self):
        """JSON flag outputs valid JSON."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl"), "--json"],
        )

        assert result.exit_code == 0
        assert '"session_id"' in result.output
        assert '"total_events"' in result.output

    def test_analyze_nonexistent_file(self):
        """Nonexistent file shows error."""
        result = runner.invoke(app, ["analyze", "/nonexistent/path.jsonl"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_analyze_with_parser_flag(self):
        """Can specify parser explicitly."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--parser",
                "claude_code",
            ],
        )

        assert result.exit_code == 0

    def test_analyze_with_unknown_parser(self):
        """Unknown parser shows error with available options."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--parser",
                "unknown",
            ],
        )

        assert result.exit_code != 0
        assert "claude_code" in result.output  # Lists available


class TestAnalyzeProject:
    def test_analyze_with_project_flag(self, tmp_path, monkeypatch):
        """Analyze --project analyzes all sessions."""
        from driftshield.cli.discovery import path_to_project_key

        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        fixture = FIXTURES_DIR / "sample_claude_code_session.jsonl"
        if fixture.exists():
            (sessions_dir / "test-session.jsonl").write_text(fixture.read_text())
        else:
            (sessions_dir / "test-session.jsonl").write_text(
                '{"type":"assistant","timestamp":1234567890000,"message":{"content":[]}}\n'
            )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["analyze", "--project"])

        assert result.exit_code == 0
        assert "test-session" in result.output or "DriftShield" in result.output
