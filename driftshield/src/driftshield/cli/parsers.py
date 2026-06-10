"""Parser registry and auto-detection for CLI."""

import json
from pathlib import Path

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.claude_desktop import ClaudeDesktopParser
from driftshield.parsers.codex_cli import CodexCliParser
from driftshield.parsers.codex_desktop import CodexDesktopParser
from driftshield.parsers.crewai import CrewAIParser
from driftshield.parsers.langchain import LangChainParser
from driftshield.parsers.openclaw import OpenClawParser
from driftshield.parsers.openclaw_trajectory import OpenClawTrajectoryParser
from driftshield.parsers.protocol import TranscriptParser


class ParserNotFoundError(Exception):
    pass


PARSERS: dict[str, type[TranscriptParser]] = {
    "claude_code": ClaudeCodeParser,
    "claude_desktop": ClaudeDesktopParser,
    "codex_cli": CodexCliParser,
    "codex_desktop": CodexDesktopParser,
    "crewai": CrewAIParser,
    "langchain": LangChainParser,
    "openclaw": OpenClawParser,
    "openclaw_trajectory": OpenClawTrajectoryParser,
}


def get_parser(name: str) -> TranscriptParser:
    if name == "auto":
        return ClaudeCodeParser()
    if name not in PARSERS:
        available = ", ".join(PARSERS.keys())
        raise ParserNotFoundError(f"Parser '{name}' not found. Available parsers: {available}")
    return PARSERS[name]()


# OpenClaw runtime trajectory records carry this envelope on every line.
# Mirrors remote_submission's shape probe.
_OPENCLAW_TRAJECTORY_KEYS = frozenset(
    {"runId", "traceId", "schemaVersion", "seq", "source"}
)


def _sniff_openclaw_trajectory(path: Path) -> bool:
    """Peek the first parseable line for the trajectory record envelope.

    Tolerates unreadable files (detection then falls back to the suffix
    rules), so non-existent paths keep their historical detection result.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return False
                return isinstance(entry, dict) and _OPENCLAW_TRAJECTORY_KEYS.issubset(
                    entry.keys()
                )
    except OSError:
        return False
    return False


def detect_parser(path: Path) -> str | None:
    path_str = str(path.resolve())
    if path_str.endswith(".trajectory.jsonl"):
        return "openclaw_trajectory"
    if ".openclaw/agents/" in path_str and "/sessions/" in path_str:
        return "openclaw"
    if ".claude/projects/" in path_str or ".claude\\projects\\" in path_str:
        return "claude_code"
    if ".claude-desktop/sessions/" in path_str or ".claude-desktop\\sessions\\" in path_str:
        return "claude_desktop"
    if ".codex/sessions/" in path_str or ".codex\\sessions\\" in path_str:
        return "codex_cli"
    if ".codex-desktop/sessions/" in path_str or ".codex-desktop\\sessions\\" in path_str:
        return "codex_desktop"
    if path.suffix == ".jsonl":
        # A trajectory file not named *.trajectory.jsonl is still a
        # trajectory; content wins over the claude_code suffix default.
        if _sniff_openclaw_trajectory(path):
            return "openclaw_trajectory"
        return "claude_code"
    return None
