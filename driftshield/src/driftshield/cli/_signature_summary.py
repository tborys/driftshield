"""Build a signature summary from a finished session file.

Shared helper between the ``telemetry submit-session`` and ``ingest``
commands. Given a session file path, parse it through the local
deterministic matcher and project the result into the public envelope
shape (:class:`driftshield.intake_contract.SignatureSummary`).

Both ``community_pack_id``/``community_pack_version`` (the bundled
community pack) and ``matcher_id``/``matcher_version`` (the deterministic
ruleset) are stamped on every entry so the receiving endpoint can keep a
public-safe audit trail of which pack and which ruleset produced the
locally derived match.

Only the six identification + provenance fields plus ``match_status``,
``confidence`` and ``confidence_band`` are emitted. Recurrence, ranking
and any private-pack identifiers stay local by construction.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from driftshield.cli.parsers import (
    ParserNotFoundError,
    detect_parser,
    get_parser,
)
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
from driftshield.db.persistence import IngestProvenance
from driftshield.intake_contract import (
    MAX_SIGNATURE_SUMMARY_ENTRIES,
    SIGNATURE_SUMMARY_VERSION,
    SignatureSummary,
    SignatureSummaryEntry,
)
from driftshield.signatures.community import load_builtin_community_pack


_MATCHER_ID = MATCHING_SCHEMA_VERSION


def _confidence_band(confidence: float | None) -> str | None:
    """Coarse band the receiving endpoint can group on without storing the raw float."""
    if confidence is None:
        return None
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    if confidence >= 0.25:
        return "low"
    return "very_low"


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if as_float < 0.0:
        return 0.0
    if as_float > 1.0:
        return 1.0
    return as_float


def _coerce_str(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_length]


def build_signature_summary_from_match(
    *,
    signature_match: dict[str, Any],
    community_pack_id: str,
    community_pack_version: str,
    matcher_id: str = _MATCHER_ID,
    matcher_version: str = RULESET_VERSION,
) -> SignatureSummary:
    """Project a ``build_signature_match_summary`` payload to the public envelope shape.

    Pure function over a known dict. Callers wire in the pack identifiers
    so the bundled-pack default can be overridden by tests.
    """
    raw_matches = signature_match.get("matches") or []
    entries: list[SignatureSummaryEntry] = []
    dropped = 0
    for raw in raw_matches:
        if not isinstance(raw, dict):
            continue
        if len(entries) >= MAX_SIGNATURE_SUMMARY_ENTRIES:
            dropped += 1
            continue

        signature_id = _coerce_str(raw.get("signature_id"), max_length=64)
        if signature_id is None:
            continue

        confidence = _coerce_confidence(raw.get("confidence"))
        entry = SignatureSummaryEntry(
            signature_id=signature_id,
            signature_version=None,
            mechanism_id=_coerce_str(raw.get("mechanism_id"), max_length=48),
            match_status="matched",
            confidence=confidence,
            confidence_band=_confidence_band(confidence),
            community_pack_id=community_pack_id,
            community_pack_version=community_pack_version,
            matcher_id=matcher_id,
            matcher_version=matcher_version,
        )
        entries.append(entry)

    if dropped:
        print(
            f"warning: signature summary truncated to "
            f"{MAX_SIGNATURE_SUMMARY_ENTRIES} entries; "
            f"{dropped} additional match(es) dropped",
            file=sys.stderr,
        )

    return SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=entries,
    )


def build_signature_summary_from_session(session_path: Path) -> SignatureSummary | None:
    """Parse a session file, run the local matcher, and project to SignatureSummary.

    Returns ``None`` when no parser can be detected for the path. Any other
    parse or analysis failure raises through to the caller so the CLI can
    surface it.
    """
    parser_name = detect_parser(session_path)
    if parser_name is None:
        return None

    try:
        parser = get_parser(parser_name)
    except ParserNotFoundError:
        return None

    events = parser.parse_file(str(session_path))
    if not events:
        return None

    session_id = uuid.uuid4()
    normalize_events(events, source_type=getattr(parser, "source_type", None), source_path=str(session_path))
    result = analyze_session(events, session_id=str(session_id))

    domain_session = DomainSession(
        id=session_id,
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp,
        external_id=events[0].session_id or None,
        status=SessionStatus.COMPLETED,
    )
    transcript_hash = hashlib.sha256(session_path.read_bytes()).hexdigest()
    provenance = IngestProvenance(
        transcript_hash=transcript_hash,
        source_session_id=events[0].session_id or None,
        source_path=str(session_path),
        parser_version=f"{parser_name}@1",
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
    return build_signature_summary_from_match(
        signature_match=signature_match,
        community_pack_id=pack.metadata.name,
        community_pack_version=pack.metadata.version,
        matcher_id=_MATCHER_ID,
        matcher_version=RULESET_VERSION,
    )


__all__ = [
    "build_signature_summary_from_match",
    "build_signature_summary_from_session",
]
