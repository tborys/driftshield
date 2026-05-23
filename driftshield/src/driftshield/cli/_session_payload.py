"""Load a session file as the envelope payload dict.

Both ``telemetry submit-session`` and ``ingest`` accept a ``--path``
pointing at the user's local session. Historically the file had to be a
single JSON object (the envelope payload). Native Claude Code sessions
ship as JSONL: a line-delimited transcript. This helper accepts either
shape transparently so users can point ``--path`` at the same JSONL the
matcher reads from when ``--include-analysis`` is set.

For JSONL inputs, each line is parsed as a JSON object and the whole
collection becomes ``payload['events']``. If any line contains a
``sessionId`` field, the first such value is also stamped on
``payload['session_id']`` so the downstream shape detector recognises
the transcript as ``claude_code``.

Lines that fail to parse are dropped silently to mirror the parser's
own tolerance for partial transcripts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_session_payload(path: Path) -> dict[str, Any]:
    """Read ``path`` and return the envelope payload dict.

    Raises:
        OSError: cannot read the file.
        ValueError: file is neither a JSON object nor parseable JSONL.
    """

    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        raise ValueError("session file is empty")

    # Path-based routing first: any ``.jsonl`` file is treated as a
    # native transcript regardless of whether its content happens to
    # parse as a single JSON object. A one-line ``.jsonl`` is still
    # JSONL: collapsing it through the JSON-object branch would emit a
    # bare transcript event in place of an envelope payload, and
    # downstream shape detection at ``remote_submission.detect_shape``
    # would fail (UnknownTranscriptShapeError). Reviewer-flagged edge
    # case on PR-118; the path-suffix gate is the load-bearing fix.
    if path.suffix.lower() == ".jsonl":
        return _load_jsonl(stripped)

    # Otherwise try parsing the whole file as a single JSON value. If
    # it succeeds the file is the legacy "pre-built envelope payload"
    # shape (e.g. produced by bin/claude_code_jsonl_to_envelope.py).
    # A successful parse to a non-dict is a hard error (arrays, scalars).
    try:
        whole = json.loads(stripped)
    except json.JSONDecodeError:
        whole = None

    if whole is not None:
        if isinstance(whole, dict):
            return whole
        raise ValueError(
            "session file must contain a JSON object at top level, not "
            f"a {type(whole).__name__}"
        )

    # Reject top-level JSON arrays detected by quick syntax check too,
    # in case a multi-line array slipped past json.loads (e.g. the file
    # opens with `[` and contains line-broken records but isn't valid
    # JSON). This keeps the operator error message clear.
    if stripped[0] == "[":
        raise ValueError(
            "session file must contain a JSON object at top level, not an array"
        )

    return _load_jsonl(stripped)


def _load_jsonl(stripped: str) -> dict[str, Any]:
    """Treat the file as line-delimited JSON, project each line into
    ``payload['events']``. Drop unparseable lines to match the native
    claude_code parser's behaviour at ``parsers/claude_code.py``.
    """

    events: list[Any] = []
    session_id: str | None = None
    for line in stripped.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(entry)
        if (
            session_id is None
            and isinstance(entry, dict)
            and isinstance(entry.get("sessionId"), str)
        ):
            session_id = entry["sessionId"]
    if not events:
        raise ValueError(
            "session file is not a JSON object and contains no parseable "
            "JSONL records"
        )
    payload: dict[str, Any] = {"events": events}
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


__all__ = ["load_session_payload"]
