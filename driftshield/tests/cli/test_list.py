"""Tests for list command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.cli.discovery import path_to_project_key


runner = CliRunner()


class TestListCommand:
    def test_list_with_project_flag(self, tmp_path, monkeypatch):
        """List shows sessions for current project."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "abc123.jsonl").write_text('{"type": "test"}')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["list", "--project"])

        assert result.exit_code == 0
        assert "abc123" in result.output

    def test_list_no_sessions(self, tmp_path, monkeypatch):
        """List shows message when no sessions found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["list", "--project"])

        assert "No sessions found" in result.output
