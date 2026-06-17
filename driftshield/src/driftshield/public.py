"""Stable public entrypoint for analysing an agent session from content.

This is the single supported function an external host (e.g. the DriftShield
intel cloud worker) calls to turn a raw agent transcript into the same verdict
the local DriftShield dashboard produces. It wraps the existing analysis chain
(parse -> normalize -> analyze_session -> build_canonical_analysis ->
deterministic match -> signature summary) behind one byte-in, verdict-out
function with no database, no FastAPI and no filesystem dependency.

Design notes
------------
* Content based, not path based. ``cli.parsers.detect_parser`` keys on the
  file path, which a cloud caller does not have. :func:`detect_source` sniffs
  the content instead, mirroring the path detector's verdicts.
* Verdict parity. The returned ``qualification`` block is exactly the local
  dashboard's qualification state (``qualified_failure`` / ``unclassified`` /
  ``not_classifiable``). A caller that persists this gets the same per run
  verdict the local dashboard shows, not a fabricated match.
* OSS safe. The ``signature_summary`` is the public envelope projection
  (:class:`driftshield.intake_contract.SignatureSummary`): identification and
  provenance plus ``match_status`` / ``confidence`` / ``confidence_band`` only.
  Recurrence, ranking and private pack identifiers stay out by construction.

The function never raises on an unparseable or empty transcript. It returns a
``raw`` result with an empty event list so a caller can persist an honest
"not classifiable" verdict rather than 500 on ingest.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from driftshield.cli._signature_summary import build_signature_summary_from_match
from driftshield.cli.parsers import ParserNotFoundError, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.canonical_analysis import build_canonical_analysis
from driftshield.core.deterministic_matching import (
    MATCHING_SCHEMA_VERSION,
    RULESET_VERSION,
    build_deterministic_match,
    build_signature_match_summary,
)
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.core.normalization import normalize_events
from driftshield.intake_contract import SIGNATURE_SUMMARY_VERSION, SignatureSummary
from driftshield.signatures.community import load_builtin_community_pack

ANALYSE_SCHEMA_VERSION = "public-analyse-v1"


@dataclass(frozen=True)
class _Provenance:
    """Minimal provenance for ``build_canonical_analysis``.

    ``build_canonical_analysis`` reads provenance by attribute only, so a small
    local dataclass avoids importing ``db.persistence`` (and its SQLAlchemy
    chain) just to carry five strings. Field names match ``IngestProvenance``.
    """

    transcript_hash: str
    source_session_id: str | None
    source_path: str | None
    parser_version: str
    ingested_at: datetime

# OpenClaw runtime trajectory records carry these envelope keys on every line.
# Mirrors cli.parsers._OPENCLAW_TRAJECTORY_KEYS so content detection agrees with
# the path based sniffer.
_OPENCLAW_TRAJECTORY_KEYS = frozenset({"runId", "traceId", "schemaVersion", "seq", "source"})

# Lifecycle ``type`` values an OpenClaw trajectory wrapper carries. Enough to tell
# the single object ``{"events": [...]}`` wrapper from any other JSON object.
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

# How many leading JSONL lines the sniffer inspects before giving up. Bounds the
# scan on large transcripts while tolerating a banner or a few corrupt lines.
_SNIFF_LINE_LIMIT = 25


def _scan_json_objects(lines: list[str]) -> list[dict[str, Any]]:
    """Return the JSON objects among the leading lines, within the limit.

    Scans several lines, not just the first: a transcript can open with a
    banner or a non-identifying record (e.g. Claude Code's
    ``file-history-snapshot``) before the line that names the format.
    """
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


def detect_source(content: str) -> str | None:
    """Detect the transcript source from content alone.

    Returns a parser name from ``cli.parsers.PARSERS`` or ``None`` when no
    format is recognised (the caller then treats the body as ``raw``). Content
    based counterpart to ``cli.parsers.detect_parser``; the cloud has no file
    path to key on.
    """
    text = content.strip()
    if not text:
        return None

    # 1. Single object OpenClaw trajectory wrapper: {"events": [ {type: ...} ]}.
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, dict):
        events = whole.get("events")
        if isinstance(events, list) and events:
            first = next((e for e in events if isinstance(e, dict)), None)
            if first is not None and (
                first.get("type") in _TRAJECTORY_EVENT_TYPES
                or _OPENCLAW_TRAJECTORY_KEYS.issubset(first.keys())
            ):
                return "openclaw_trajectory"

    # 2. JSONL formats. Scan several leading objects; a transcript can open with
    # a non-identifying record before the line that names the format.
    objects = _scan_json_objects(text.split("\n"))
    if not objects:
        return None

    types = {obj.get("type") for obj in objects}

    # OpenClaw trajectory JSONL (records carry the run/trace envelope).
    if any(_OPENCLAW_TRAJECTORY_KEYS.issubset(obj.keys()) for obj in objects) or (
        types & _TRAJECTORY_EVENT_TYPES
    ):
        return "openclaw_trajectory"

    # Claude Code: records keyed on sessionId + parentUuid + message, or its
    # distinctive line types. Checked before the bare-type OpenClaw probe
    # because Claude Code also emits ``user``/``assistant`` types.
    if (
        types & {"file-history-snapshot", "progress", "summary"}
        or any(
            obj.get("type") in {"assistant", "user"}
            and "sessionId" in obj
            and ("parentUuid" in obj or "message" in obj)
            for obj in objects
        )
    ):
        return "claude_code"

    # OpenClaw session transcript: lifecycle/message records keyed on a bare
    # type, without Claude Code's sessionId/parentUuid envelope.
    if types & {"session", "message", "custom"}:
        return "openclaw"

    return None


def _trajectory_wrapper_to_jsonl(content: str) -> str:
    """Unwrap a single object ``{"events": [...]}`` trajectory to JSONL.

    The OpenClaw trajectory parser consumes one record per line. The persisted
    cloud payload is a single object whose ``events`` array holds the records,
    so flatten it. A body that is not the wrapper shape is returned unchanged
    (already JSONL, or not a trajectory at all).
    """
    try:
        whole = json.loads(content)
    except json.JSONDecodeError:
        return content
    if isinstance(whole, dict) and isinstance(whole.get("events"), list):
        return "\n".join(json.dumps(event) for event in whole["events"])
    return content


def _empty_canonical(source_format: str, *, reason: str) -> dict[str, Any]:
    """Build an honest not classifiable verdict for an unparseable transcript."""
    return {
        "schema_version": ANALYSE_SCHEMA_VERSION,
        "source_format": source_format,
        "qualification": {
            "qualification_state": "not_classifiable",
            "qualification_reasons": [reason],
        },
        "signature_summary": SignatureSummary(
            schema_version=SIGNATURE_SUMMARY_VERSION, matches=[]
        ).model_dump(),
        "canonical_analysis": None,
        "event_count": 0,
    }


def analyse(
    content: str | bytes,
    *,
    source: str = "auto",
    source_session_id: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    """Analyse an agent transcript and return the canonical verdict.

    Parameters
    ----------
    content:
        The raw transcript. JSONL for most sources; a single object wrapper for
        the OpenClaw trajectory cloud shape. ``bytes`` are decoded as UTF-8.
    source:
        A parser name (``"claude_code"``, ``"openclaw"``,
        ``"openclaw_trajectory"``, ...) or ``"auto"`` to detect from content.
    source_session_id / source_path:
        Optional provenance, stamped into the canonical analysis.

    Returns
    -------
    dict
        ``{schema_version, source_format, qualification, signature_summary,
        canonical_analysis, event_count}``. ``qualification.qualification_state``
        is the same verdict the local dashboard shows. Never raises on an empty
        or unparseable transcript: it returns a ``not_classifiable`` verdict so
        ingest is never broken.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    resolved = source.replace("-", "_") if source else "auto"
    if resolved == "auto":
        detected = detect_source(content)
        if detected is None:
            return _empty_canonical("raw", reason="unrecognised_source_format")
        resolved = detected

    try:
        parser = get_parser(resolved)
    except ParserNotFoundError:
        return _empty_canonical("raw", reason="unsupported_source_format")

    parse_input = content
    if resolved == "openclaw_trajectory":
        parse_input = _trajectory_wrapper_to_jsonl(content)

    try:
        events = parser.parse(parse_input)
    except Exception:  # noqa: BLE001 - a malformed transcript is data, not a crash
        return _empty_canonical(resolved, reason="parse_failed")

    if not events:
        return _empty_canonical(resolved, reason="no_events")

    session_id = uuid.uuid4()
    normalize_events(
        events,
        source_type=getattr(parser, "source_type", resolved),
        source_path=source_path,
    )
    result = analyze_session(events, session_id=str(session_id))

    domain_session = DomainSession(
        id=session_id,
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp,
        external_id=events[0].session_id or source_session_id,
        status=SessionStatus.COMPLETED,
    )
    provenance = _Provenance(
        transcript_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_session_id=events[0].session_id or source_session_id,
        source_path=source_path,
        parser_version=f"{resolved}@1",
        ingested_at=datetime.now(timezone.utc),
    )

    canonical_analysis = build_canonical_analysis(
        session=domain_session,
        result=result,
        provenance=provenance,
    )
    deterministic_match = build_deterministic_match(
        canonical_analysis=canonical_analysis,
        result=result,
    )
    signature_match = build_signature_match_summary(deterministic_match)

    pack = load_builtin_community_pack()
    signature_summary = build_signature_summary_from_match(
        signature_match=signature_match,
        community_pack_id=pack.metadata.name,
        community_pack_version=pack.metadata.version,
        matcher_id=MATCHING_SCHEMA_VERSION,
        matcher_version=RULESET_VERSION,
    )

    qualification = canonical_analysis.get("qualification", {})
    return {
        "schema_version": ANALYSE_SCHEMA_VERSION,
        "source_format": resolved,
        "qualification": {
            "qualification_state": qualification.get("qualification_state"),
            "qualification_reasons": qualification.get("qualification_reasons", []),
        },
        "signature_summary": signature_summary.model_dump(),
        "canonical_analysis": canonical_analysis,
        "event_count": len(result.events),
    }


__all__ = ["analyse", "detect_source", "ANALYSE_SCHEMA_VERSION"]
