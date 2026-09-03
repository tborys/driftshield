"""Parser registry and the one format detector (internal).

Content decides the format; the path is only a hint consulted when the
content is inconclusive. Every entry path (CLI, batch, API ingest, connector
watcher, library callers) reaches this module through
:func:`driftshield.public.analyse_run`; nothing here is public API.
"""

from __future__ import annotations

import json
from typing import Any

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.claude_desktop import ClaudeDesktopParser
from driftshield.parsers.codex_cli import CodexCliParser, is_rollout_record
from driftshield.parsers.codex_desktop import CodexDesktopParser
from driftshield.parsers.crewai import CrewAIParser
from driftshield.parsers.langchain import LangChainParser
from driftshield.parsers.openclaw import OpenClawParser
from driftshield.parsers.openclaw_trajectory import OpenClawTrajectoryParser
from driftshield.parsers.protocol import TranscriptParser

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
    if name not in PARSERS:
        available = ", ".join(PARSERS)
        raise KeyError(f"Parser '{name}' not found. Available parsers: {available}")
    return PARSERS[name]()


# OpenClaw runtime trajectory records carry these envelope keys on every line.
_OPENCLAW_TRAJECTORY_KEYS = frozenset({"runId", "traceId", "schemaVersion", "seq", "source"})

# Lifecycle ``type`` values an OpenClaw trajectory carries.
_TRAJECTORY_EVENT_TYPES = frozenset(
    {
        "session.started",
        "session.ended",
        "trace.metadata",
        "trace.artifacts",
        "context.compiled",
        "prompt.submitted",
        "model.completed",
    }
)

# How many leading records the sniffer inspects before giving up. Bounds the
# scan on large transcripts while tolerating a banner or a few corrupt lines.
_SNIFF_LINE_LIMIT = 25

# Directory conventions of the native session stores. Only consulted when the
# content itself is inconclusive.
_PATH_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    ((".openclaw/agents/", "/sessions/"), "openclaw"),
    ((".claude/projects/",), "claude_code"),
    ((".claude\\projects\\",), "claude_code"),
    ((".claude-desktop/sessions/",), "claude_desktop"),
    ((".claude-desktop\\sessions\\",), "claude_desktop"),
    ((".codex/sessions/",), "codex_cli"),
    ((".codex\\sessions\\",), "codex_cli"),
    ((".codex-desktop/sessions/",), "codex_desktop"),
    ((".codex-desktop\\sessions\\",), "codex_desktop"),
)


def load_json_document(text: str) -> Any:
    """Return the whole text parsed as one JSON document, or ``None``."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def leading_json_objects(lines: list[str]) -> list[dict[str, Any]]:
    """Return the JSON objects among the leading lines, within the sniff limit."""
    objects: list[dict[str, Any]] = []
    for line in lines[:_SNIFF_LINE_LIMIT]:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            objects.append(entry)
    return objects


def _detect_single_document(whole: Any) -> str | None:
    """Detect formats that ship as one JSON document (object or array)."""
    if isinstance(whole, list):
        first = next((e for e in whole if isinstance(e, dict)), None)
        if first is not None and ("run_type" in first or ("trace_id" in first and "inputs" in first)):
            return "langchain"
        return None

    if not isinstance(whole, dict):
        return None

    events = whole.get("events")
    if isinstance(events, list) and events:
        first = next((e for e in events if isinstance(e, dict)), None)
        if first is not None and (
            first.get("type") in _TRAJECTORY_EVENT_TYPES
            or _OPENCLAW_TRAJECTORY_KEYS.issubset(first.keys())
        ):
            return "openclaw_trajectory"

    if "tasks" in whole and ("crew_name" in whole or "run_id" in whole):
        return "crewai"

    # Codex / Claude desktop: a single-session object with a messages[] array.
    # Content shape is the reliable discriminator: desktop-codex uses a content
    # LIST of {type, text} parts, claude-desktop a content STRING.
    messages = whole.get("messages")
    if isinstance(messages, list) and messages:
        first_msg = next((m for m in messages if isinstance(m, dict)), None)
        if first_msg is not None and "role" in first_msg:
            sample = next(
                (m.get("content") for m in messages if isinstance(m, dict) and m.get("content") is not None),
                None,
            )
            if isinstance(sample, list):
                return "codex_desktop"
            if isinstance(sample, str):
                return "claude_desktop"
            return "claude_desktop" if "session_id" in whole else "codex_desktop"

    return None


def _detect_records(objects: list[dict[str, Any]]) -> str | None:
    """Detect the line-delimited formats from their leading records."""
    if not objects:
        return None
    types = {obj.get("type") for obj in objects}

    if any(_OPENCLAW_TRAJECTORY_KEYS.issubset(obj.keys()) for obj in objects) or (
        types & _TRAJECTORY_EVENT_TYPES
    ):
        return "openclaw_trajectory"

    # Claude Code: records keyed on sessionId + parentUuid/message, or its
    # distinctive line types. Checked before the bare-type probes because
    # Claude Code also emits ``user``/``assistant`` types.
    if types & {"file-history-snapshot", "progress", "summary"} or any(
        obj.get("type") in {"assistant", "user"}
        and "sessionId" in obj
        and ("parentUuid" in obj or "message" in obj)
        for obj in objects
    ):
        return "claude_code"

    # Codex: the rollout envelope (``{"timestamp","type","payload"}`` records
    # under ~/.codex/sessions) or the older flat ``message`` lines.
    if (
        "session_meta" in types
        or any(is_rollout_record(obj) for obj in objects)
        or any("session_id" in obj and obj.get("type") in {"session_meta", "message"} for obj in objects)
    ):
        return "codex_cli"

    if types & {"session", "message", "custom"}:
        return "openclaw"

    return None


def detect_from_content(text: str) -> str | None:
    """Detect the transcript format from content alone."""
    stripped = text.strip()
    if not stripped:
        return None

    whole = load_json_document(stripped)
    if whole is not None:
        single = _detect_single_document(whole)
        if single is not None:
            return single
        # A wrapper object carrying line records under ``events`` (the
        # pre-built envelope shape) is detected from those records.
        if isinstance(whole, dict) and isinstance(whole.get("events"), list):
            return _detect_records([e for e in whole["events"] if isinstance(e, dict)][:_SNIFF_LINE_LIMIT])
        # Anything else that parsed as one document may still be a single
        # line of a line-delimited format; fall through to the line scan.

    return _detect_records(leading_json_objects(stripped.split("\n")))


def detect_from_path(path_hint: str) -> str | None:
    """Detect the format from the native session store conventions in a path."""
    if path_hint.endswith(".trajectory.jsonl"):
        return "openclaw_trajectory"
    for needles, name in _PATH_HINTS:
        if all(needle in path_hint for needle in needles):
            return name
    if path_hint.endswith(".jsonl"):
        return "claude_code"
    return None


def detect_format(text: str, *, path_hint: str | None = None) -> tuple[str | None, str | None]:
    """The one format detector: content decides, the path is a hint.

    Returns ``(format, warning)``. The warning names a path hint that
    disagreed with the content, so callers can surface it without failing.
    """
    from_content = detect_from_content(text)
    from_path = detect_from_path(path_hint) if path_hint else None
    if from_content is not None:
        warning = None
        if from_path is not None and from_path != from_content:
            warning = f"path suggested '{from_path}' but content detected '{from_content}'"
        return from_content, warning
    return from_path, None


__all__ = ["PARSERS", "detect_format", "get_parser", "leading_json_objects", "load_json_document"]
