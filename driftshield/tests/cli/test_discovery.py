"""Tests for session discovery."""

from pathlib import Path
from datetime import datetime, timezone

import pytest

from driftshield.cli.discovery import (
    get_claude_projects_dir,
    path_to_project_key,
    discover_sessions,
    resolve_session,
    SessionInfo,
)


class TestPathToProjectKey:
    def test_converts_path_to_key(self):
        """Converts absolute path to Claude project key format."""
        path = Path("/Users/tom/github/my-repo")
        key = path_to_project_key(path)
        assert key == "-Users-tom-github-my-repo"

    def test_handles_different_paths(self):
        """Works with various path formats."""
        assert path_to_project_key(Path("/foo/bar")) == "-foo-bar"
        assert path_to_project_key(Path("/a/b/c/d")) == "-a-b-c-d"


class TestDiscoverSessions:
    def test_returns_empty_when_no_sessions(self, tmp_path):
        """Returns empty list when no sessions found."""
        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")
        assert sessions == []

    def test_finds_jsonl_sessions(self, tmp_path):
        """Finds JSONL session files."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        (sessions_dir / "abc123.jsonl").write_text('{"type": "test"}')
        (sessions_dir / "def456.jsonl").write_text('{"type": "test"}')

        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")

        assert len(sessions) == 2
        assert all(isinstance(s, SessionInfo) for s in sessions)

    def test_sorts_by_modification_time(self, tmp_path):
        """Sessions sorted newest first."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        old = sessions_dir / "old.jsonl"
        new = sessions_dir / "new.jsonl"

        old.write_text('{"type": "test"}')
        new.write_text('{"type": "test"}')

        import os
        import time
        os.utime(old, (time.time() - 100, time.time() - 100))

        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")

        assert sessions[0].path.name == "new.jsonl"
        assert sessions[1].path.name == "old.jsonl"


class TestResolveSession:
    def test_resolves_full_path(self, tmp_path):
        """Full path resolves directly."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text('{"type": "test"}')

        path = resolve_session(str(session_file), project_dir=tmp_path)
        assert path == session_file

    def test_resolves_session_id(self, tmp_path):
        """Session ID resolves via discovery."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "abc123-def.jsonl"
        session_file.write_text('{"type": "test"}')

        path = resolve_session(
            "abc123-def",
            project_dir=tmp_path,
            claude_base=tmp_path / ".claude",
        )
        assert path == session_file

    def test_resolves_index(self, tmp_path):
        """Numeric index resolves to nth session."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        (sessions_dir / "first.jsonl").write_text('{"type": "test"}')
        (sessions_dir / "second.jsonl").write_text('{"type": "test"}')

        path = resolve_session(
            "1",
            project_dir=tmp_path,
            claude_base=tmp_path / ".claude",
        )
        assert path is not None
