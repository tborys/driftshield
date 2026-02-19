"""Parser registry and auto-detection for CLI."""

from pathlib import Path

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.protocol import TranscriptParser


class ParserNotFoundError(Exception):
    """Raised when requested parser is not found."""

    pass


PARSERS: dict[str, type[TranscriptParser]] = {
    "claude_code": ClaudeCodeParser,
}


def get_parser(name: str) -> TranscriptParser:
    """Get a parser instance by name.

    Args:
        name: Parser name ('auto', 'claude_code', etc.)

    Returns:
        Parser instance

    Raises:
        ParserNotFoundError: If parser not found
    """
    if name == "auto":
        return ClaudeCodeParser()

    if name not in PARSERS:
        available = ", ".join(PARSERS.keys())
        raise ParserNotFoundError(
            f"Parser '{name}' not found. Available parsers: {available}"
        )

    return PARSERS[name]()


def detect_parser(path: Path) -> str | None:
    """Detect parser type from file path.

    Args:
        path: Path to the file

    Returns:
        Parser name or None if cannot detect
    """
    path_str = str(path.resolve())
    if ".claude/projects/" in path_str or ".claude\\projects\\" in path_str:
        return "claude_code"

    if path.suffix == ".jsonl":
        return "claude_code"

    return None
