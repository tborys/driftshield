"""Session discovery helpers for local transcript sources."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SessionInfo:
    """Information about a discovered session."""

    path: Path
    session_id: str
    modified_at: datetime
    size_bytes: int

    @property
    def age_description(self) -> str:
        """Human-readable age description."""
        delta = datetime.now(timezone.utc) - self.modified_at
        if delta.days > 1:
            return f"{delta.days} days ago"
        elif delta.days == 1:
            return "yesterday"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"


def get_claude_projects_dir(claude_base: Optional[Path] = None) -> Path:
    """Get the Claude Code projects directory."""
    if claude_base is None:
        claude_base = Path.home() / ".claude"
    return claude_base / "projects"


def path_to_project_key(path: Path) -> str:
    """Convert a filesystem path to Claude project key format.

    /Users/tom/github/repo -> -Users-tom-github-repo
    """
    resolved = path.resolve()
    return str(resolved).replace("/", "-").replace("\\", "-")


def discover_sessions(
    project_dir: Path,
    claude_base: Optional[Path] = None,
) -> list[SessionInfo]:
    """Discover Claude Code sessions for a project directory.

    Args:
        project_dir: The project directory to find sessions for
        claude_base: Base claude directory (default: ~/.claude)

    Returns:
        List of SessionInfo, sorted by modification time (newest first)
    """
    projects_dir = get_claude_projects_dir(claude_base)
    project_key = path_to_project_key(project_dir)
    sessions_path = projects_dir / project_key

    return discover_sessions_in_path(sessions_path)


def discover_sessions_in_path(sessions_path: Path) -> list[SessionInfo]:
    """Discover session files from a concrete sessions directory."""
    if not sessions_path.exists():
        return []

    sessions = []
    for file in sessions_path.glob("*.jsonl"):
        stat = file.stat()
        sessions.append(
            SessionInfo(
                path=file,
                session_id=file.stem,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                size_bytes=stat.st_size,
            )
        )

    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions


def resolve_session(
    identifier: str,
    project_dir: Optional[Path] = None,
    claude_base: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a session identifier to a file path.

    Identifier can be:
    - Full path to a .jsonl file
    - Session ID (filename without extension)
    - Numeric index (1 = most recent)

    Args:
        identifier: The session identifier
        project_dir: Project directory for discovery (default: cwd)
        claude_base: Base claude directory (default: ~/.claude)

    Returns:
        Path to session file, or None if not found
    """
    path = Path(identifier).expanduser()
    if path.exists() and path.is_file():
        return path.resolve()

    if project_dir is None:
        project_dir = Path.cwd()

    sessions = discover_sessions(project_dir, claude_base)
    if not sessions:
        return None

    if identifier.isdigit():
        index = int(identifier) - 1
        if 0 <= index < len(sessions):
            return sessions[index].path
        return None

    for session in sessions:
        if session.session_id == identifier or session.session_id.startswith(identifier):
            return session.path

    return None
