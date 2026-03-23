"""Parser registry and auto-detection for CLI."""

from pathlib import Path

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.claude_desktop import ClaudeDesktopParser
from driftshield.parsers.codex_cli import CodexCliParser
from driftshield.parsers.codex_desktop import CodexDesktopParser
from driftshield.parsers.openclaw import OpenClawParser
from driftshield.parsers.protocol import TranscriptParser


class ParserNotFoundError(Exception):
    pass


PARSERS: dict[str, type[TranscriptParser]] = {
    "claude_code": ClaudeCodeParser,
    "claude_desktop": ClaudeDesktopParser,
    "codex_cli": CodexCliParser,
    "codex_desktop": CodexDesktopParser,
    "openclaw": OpenClawParser,
}


def get_parser(name: str) -> TranscriptParser:
    if name == "auto":
        return ClaudeCodeParser()
    if name not in PARSERS:
        available = ", ".join(PARSERS.keys())
        raise ParserNotFoundError(f"Parser '{name}' not found. Available parsers: {available}")
    return PARSERS[name]()


def detect_parser(path: Path) -> str | None:
    path_str = str(path.resolve())
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
        return "claude_code"
    return None
