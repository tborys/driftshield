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
