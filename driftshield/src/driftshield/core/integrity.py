"""OSS-safe integrity scoring for stored investigation sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.models import Session as DomainSession

if TYPE_CHECKING:
    from driftshield.db.persistence import IngestProvenance

INTEGRITY_SCHEMA_VERSION = "phase3e.v1"
INTEGRITY_POLICY_VERSION = "phase3e.v1.default"
OSS_V1_PATTERN_INTEGRITY_PLACEHOLDER = 0.95


def build_integrity_summary(
    session: DomainSession,
    result: AnalysisResult,
    provenance: IngestProvenance | None,
) -> dict[str, Any]:
    """Build the persisted OSS-safe integrity summary for one investigated run."""

    total_events = result.total_events
    flagged_events = result.flagged_events

    structural_score, structural_reasons = _structural_score(result)
    semantic_score, semantic_reasons = _semantic_score(result)
    source_factor, source_reasons = _source_factor(session, provenance)

    final_learning_weight = round(
        structural_score
        * semantic_score
        * source_factor
        * OSS_V1_PATTERN_INTEGRITY_PLACEHOLDER,
        4,
    )

    trust_band = _trust_band(final_learning_weight)
    integrity_reasons = [
        *structural_reasons,
        *semantic_reasons,
        *source_reasons,
        "pattern_integrity_placeholder_oss_v1",
    ]

    return {
        "integrity_schema_version": INTEGRITY_SCHEMA_VERSION,
        "trust_band": trust_band,
        "structural_score": structural_score,
        "semantic_score": semantic_score,
        "source_factor": source_factor,
        "pattern_integrity_score": OSS_V1_PATTERN_INTEGRITY_PLACEHOLDER,
        "final_learning_weight": final_learning_weight,
        "integrity_reasons": integrity_reasons,
        "requires_review": trust_band != "trusted",
        "integrity_evaluated_at": _evaluated_at(session, provenance).isoformat(),
        "integrity_policy_version": INTEGRITY_POLICY_VERSION,
        "evidence_counts": {
            "total_events": total_events,
            "flagged_events": flagged_events,
        },
        "pattern_integrity_note": (
            "OSS v1 uses a conservative placeholder because private Pattern Object "
            "promotion and recurrence logic are out of scope."
        ),
    }


def build_integrity_provenance(
    summary: dict[str, Any],
    provenance: IngestProvenance | None,
) -> dict[str, Any]:
    """Build the public provenance payload for the integrity decision."""

    parser_version = provenance.parser_version if provenance else None
    return {
        "source_type": _source_type(parser_version),
        "source_session_id": provenance.source_session_id if provenance else None,
        "source_path": provenance.source_path if provenance else None,
        "parser_version": parser_version,
        "transcript_hash": provenance.transcript_hash if provenance else None,
        "ingested_at": provenance.ingested_at.isoformat() if provenance else None,
        "integrity_policy_version": summary["integrity_policy_version"],
        "integrity_schema_version": summary["integrity_schema_version"],
        "integrity_evaluated_at": summary["integrity_evaluated_at"],
        "evidence_counts": summary["evidence_counts"],
    }


def _structural_score(result: AnalysisResult) -> tuple[float, list[str]]:
    if result.total_events == 0:
        return 0.0, ["no_events"]

    missing_actions = sum(1 for event in result.events if not event.action)
    missing_timestamps = sum(1 for event in result.events if event.timestamp is None)
    completeness = 1 - ((missing_actions + missing_timestamps) / (2 * result.total_events))
    score = round(max(0.0, min(1.0, completeness)), 4)

    reasons: list[str] = []
    if missing_actions:
        reasons.append("missing_event_actions")
    if missing_timestamps:
        reasons.append("missing_event_timestamps")
    return score, reasons


def _semantic_score(result: AnalysisResult) -> tuple[float, list[str]]:
    if result.total_events == 0:
        return 0.0, ["no_events"]

    evidence_rich_events = sum(
        1
        for event in result.events
        if event.inputs or event.outputs or event.metadata
    )
    coverage = evidence_rich_events / result.total_events
    score = round(0.6 + (0.4 * coverage), 4)

    reasons: list[str] = []
    if coverage < 0.75:
        reasons.append("sparse_event_evidence")
    return score, reasons


def _source_factor(
    session: DomainSession,
    provenance: IngestProvenance | None,
) -> tuple[float, list[str]]:
    score = 0.4
    reasons: list[str] = []

    if provenance and provenance.transcript_hash:
        score += 0.25
    else:
        reasons.append("missing_transcript_hash")

    if provenance and provenance.parser_version:
        score += 0.2
    else:
        reasons.append("missing_parser_version")

    if provenance and provenance.source_session_id:
        score += 0.1
    if provenance and provenance.source_path:
        score += 0.05
    if not provenance or (not provenance.source_session_id and not provenance.source_path):
        reasons.append("missing_source_locator")

    if session.external_id:
        score += 0.05

    return round(min(score, 1.0), 4), reasons


def _trust_band(final_learning_weight: float) -> str:
    if final_learning_weight >= 0.70:
        return "trusted"
    if final_learning_weight >= 0.40:
        return "provisional"
    return "quarantined"


def _evaluated_at(session: DomainSession, provenance: IngestProvenance | None) -> datetime:
    if provenance is not None:
        return provenance.ingested_at
    if session.ended_at is not None:
        return session.ended_at
    return session.started_at or datetime.now(timezone.utc)


def _source_type(parser_version: str | None) -> str | None:
    if not parser_version:
        return None
    return parser_version.split("@", 1)[0]
