"""Tests for inspect command."""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestInspectCommand:
    def test_inspect_node_by_path(self):
        """Can inspect a specific node."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "0",
            ],
        )

        assert result.exit_code == 0
        assert "Node #0" in _strip_ansi(result.output)

    def test_inspect_with_path_to_root(self):
        """Path to root shows ancestry."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "1",
                "--path-to-root",
            ],
        )

        assert result.exit_code == 0
        assert "Path to Root" in _strip_ansi(result.output)

    def test_inspect_invalid_node(self):
        """Invalid node number shows error."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "9999",
            ],
        )

        assert result.exit_code != 0
        assert "not found" in _strip_ansi(result.output).lower()

    def test_inspect_with_json(self):
        """JSON output returns valid JSON."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "0",
                "--json",
            ],
        )

        assert result.exit_code == 0
        assert '"action"' in _strip_ansi(result.output)
