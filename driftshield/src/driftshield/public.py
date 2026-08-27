"""The public door: ``analyse_run`` and ``submit``.

These two calls are the whole supported surface of the DriftShield engine.
Format detection, parsing, signature evaluation, redaction and transport are
internal to them. Every CLI command, the self-hosted API ingest, the connector
watcher and library callers all go through this module.

* :func:`analyse_run` is synchronous and pure: bytes (or an event sequence) in,
  an :class:`AnalysedRun` out. No network, no database, no filesystem.
* :func:`submit` is the only way anything leaves the machine. It sends the
  run's redacted transcript, never the raw one.

See ``docs/public-api.md`` for the integrator-facing contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from driftshield.core.analysis.session import AnalysisResult, analyze_session
from driftshield.core.canonical_analysis import DECLARED_ENVIRONMENTS, build_canonical_analysis
from driftshield.core.deterministic_matching import (
    MATCHING_SCHEMA_VERSION,
    RULESET_VERSION,
    build_deterministic_match,
    build_signature_match_summary,
)
from driftshield.core.models import (
    CanonicalEvent,
    EnvironmentClass,
    RunProvenance,
    Session,
    SessionStatus,
)
from driftshield.core.normalization import normalize_events
from driftshield.intake_contract import (
    DEFAULT_WORKFLOW_REFERENCE,
    MAX_SIGNATURE_SUMMARY_ENTRIES,
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SIGNATURE_SUMMARY_VERSION,
    SUPPORTED_CONTRACT_VERSION,
    SignatureSummary,
    SignatureSummaryEntry,
)
from driftshield.parsers.registry import (
    PARSERS,
    detect_format,
    get_parser,
    load_json_document,
)
from driftshield.recursive_redactor import REDACTION_RULESET_VERSION, REDACTOR_VERSION, redact
from driftshield.remote_submission import (
    OssRemoteSubmissionConfig,
    RemoteSubmissionError,
    build_oss_submission_request,
    post_oss_submission,
)
from driftshield.remote_upload import (
    INLINE_PAYLOAD_THRESHOLD_BYTES,
    OssUploadConfig,
    TeamsUploadConfig,
    submit_oss_via_presigned_upload,
    submit_teams_via_presigned_upload,
)
from driftshield.signatures.community import load_builtin_community_pack
from driftshield.telemetry import TelemetryService, effective_oss_intake_url

Visibility = Literal["community", "workspace"]

# Accepted spellings for the two destinations. The CLI's historical
# ``--tier oss|teams`` names map onto the same two visibilities.
_VISIBILITY_ALIASES: dict[str, str] = {
    "community": "community",
    "oss": "community",
    "workspace": "workspace",
    "teams": "workspace",
}

# Formats whose native transcript is line-delimited JSON. The shareable copy of
# one of these is the record list under ``events`` (plus the promoted session
# id), the same shape the submit path has always uploaded.
_LINE_FORMATS = frozenset({"claude_code", "codex_cli", "openclaw", "openclaw_trajectory"})

# How many unreadable lines are named individually before the rest are counted.
_WARNING_DETAIL_LIMIT = 10

_ENVIRONMENT_KEY = "environment"

SubmitError = RemoteSubmissionError


class NoParseableEventsError(ValueError):
    """``analyse_run`` could not read a single event from the content.

    ``reason`` is one of ``empty``, ``unrecognised_format``, ``parse_failed``
    or ``no_events``; ``warnings`` carries whatever was learned on the way.
    """

    def __init__(self, reason: str, message: str, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.warnings = list(warnings or [])


class UnsupportedFormatError(ValueError):
    """An explicit ``format`` name is not one the engine knows."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing that went wrong, anchored to an event of the run.

    ``kind`` is ``"risk"`` (a flagged event; ``risks`` names the flags) or
    ``"break_point"`` (the inflection the analysis identified).
    """

    kind: str
    event_index: int
    event_id: str
    risks: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class SignatureHit:
    """A community signature the deterministic matcher matched on this run."""

    signature_id: str
    mechanism_id: str | None
    confidence: float | None
    confidence_band: str | None
    summary: str | None
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysedRun:
    """The result of :func:`analyse_run`. Local only until :func:`submit`.

    The contract fields are ``events``, ``findings``, ``signature_hits``,
    ``redacted_transcript``, ``source``, ``detected_format``, ``warnings``,
    ``qualification_state`` and ``qualification_reasons``. The remaining
    fields are engine detail kept on the run for the CLI and API skins.
    """

    run_id: uuid.UUID
    events: list[CanonicalEvent]
    findings: list[Finding]
    signature_hits: list[SignatureHit]
    redacted_transcript: dict[str, Any]
    source: str | None
    detected_format: str
    warnings: list[str]
    qualification_state: str | None
    qualification_reasons: list[str]
    # Engine detail (local only).
    transcript: dict[str, Any]
    redaction_manifest: dict[str, Any]
    provenance: RunProvenance
    session: Session
    analysis: AnalysisResult
    canonical_analysis: dict[str, Any] = field(repr=False)

    @property
    def session_observed_at(self) -> datetime:
        """The run's own end time: the last event's timestamp, not ingest time."""
        return self.events[-1].timestamp

    @property
    def signature_summary(self) -> SignatureSummary:
        """The hits projected to the envelope shape a submission carries."""
        pack = load_builtin_community_pack()
        entries = [
            SignatureSummaryEntry(
                signature_id=hit.signature_id[:64],
                mechanism_id=hit.mechanism_id[:48] if hit.mechanism_id else None,
                match_status="matched",
                confidence=hit.confidence,
                confidence_band=hit.confidence_band,
                community_pack_id=pack.metadata.name,
                community_pack_version=pack.metadata.version,
                matcher_id=MATCHING_SCHEMA_VERSION,
                matcher_version=RULESET_VERSION,
            )
            for hit in self.signature_hits[:MAX_SIGNATURE_SUMMARY_ENTRIES]
        ]
        return SignatureSummary(schema_version=SIGNATURE_SUMMARY_VERSION, matches=entries)


@dataclass(frozen=True, slots=True)
class SubmitReceipt:
    submission_id: str
    processing_status: str
    visibility: str
    server_contract_version: str | None
    deprecation_warning: str | None


# --------------------------------------------------------------------------- #
# analyse_run
# --------------------------------------------------------------------------- #


def analyse_run(
    content: bytes | str | Iterable[CanonicalEvent],
    *,
    source: str | None = None,
    format: str | None = None,
    run_id: uuid.UUID | None = None,
) -> AnalysedRun:
    """Analyse one agent run. Synchronous, pure, local.

    ``content`` is the raw transcript (``bytes`` or ``str``) or an already
    parsed event sequence. ``source`` is a provenance label, usually the file
    path; it is only a hint for format detection, the content decides.
    ``format`` forces a parser instead of detecting one. ``run_id`` fixes the
    run identity (event ids derive from it) so re-analysing the same content
    yields the same ids.

    Raises :class:`UnsupportedFormatError` for an unknown ``format`` name and
    :class:`NoParseableEventsError` when no event could be read.
    """
    if format is not None:
        format = format.replace("-", "_")
        if format not in PARSERS:
            raise UnsupportedFormatError(
                f"Unsupported format: {format}. Available parsers: {', '.join(PARSERS)}"
            )

    run_id = run_id or uuid.uuid4()
    if isinstance(content, (bytes, str)):
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        events, detected, transcript, warnings = _parse_bytes(raw, source=source, format=format)
    else:
        events = list(content)
        detected = format or _events_format(events)
        transcript = {"events": [_event_record(event) for event in events]}
        raw = json.dumps(transcript, sort_keys=True, default=str).encode("utf-8")
        warnings = []

    if not events:
        raise NoParseableEventsError(
            "no_events",
            f"parsed as '{detected}' but found zero events",
            warnings,
        )

    _stabilise_event_ids(events, run_id)
    normalize_events(events, source_type=detected, source_path=source)
    analysis = analyze_session(events, session_id=events[0].session_id or str(run_id))

    session = Session(
        id=run_id,
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp,
        external_id=events[0].session_id or None,
        status=SessionStatus.COMPLETED,
    )
    provenance = RunProvenance(
        transcript_hash=hashlib.sha256(raw).hexdigest(),
        source_session_id=events[0].session_id or None,
        source_path=source,
        parser_version=f"{detected}@1",
        ingested_at=datetime.now(timezone.utc),
    )
    canonical = build_canonical_analysis(session=session, result=analysis, provenance=provenance)
    match_summary = build_signature_match_summary(
        build_deterministic_match(canonical_analysis=canonical, result=analysis)
    )
    qualification = canonical.get("qualification") or {}

    redaction = redact(transcript)
    redacted = redaction.payload
    if not isinstance(redacted, dict):
        raise NoParseableEventsError("parse_failed", "redacted transcript is not a JSON object", warnings)

    return AnalysedRun(
        run_id=run_id,
        events=analysis.events,
        findings=_findings(analysis),
        signature_hits=_signature_hits(match_summary),
        redacted_transcript=redacted,
        source=source,
        detected_format=detected,
        warnings=warnings,
        qualification_state=qualification.get("qualification_state"),
        qualification_reasons=list(qualification.get("qualification_reasons") or []),
        transcript=transcript,
        redaction_manifest={
            "manifest_version": REDACTION_MANIFEST_VERSION,
            "redaction_applied": True,
            "redacted_fields": sorted(REQUIRED_REDACTION_FIELDS),
            "redactor_version": REDACTOR_VERSION,
            "redaction_ruleset_version": REDACTION_RULESET_VERSION,
            "entries": [
                {"path": e.path, "category": e.category, "sample_hash": e.sample_hash}
                for e in redaction.entries
            ],
        },
        provenance=provenance,
        session=session,
        analysis=analysis,
        canonical_analysis=canonical,
    )


def _parse_bytes(
    raw: bytes, *, source: str | None, format: str | None
) -> tuple[list[CanonicalEvent], str, dict[str, Any], list[str]]:
    warnings: list[str] = []
    text = raw.decode("utf-8", errors="replace")
    replaced = text.count("�")
    if replaced:
        warnings.append(f"{replaced} undecodable byte sequence(s) replaced while decoding as UTF-8")
    if not text.strip():
        raise NoParseableEventsError("empty", "transcript is empty", warnings)

    detected = format
    if detected is None:
        detected, hint_warning = detect_format(text, path_hint=source)
        if hint_warning:
            warnings.append(hint_warning)
    if detected is None:
        raise NoParseableEventsError(
            "unrecognised_format",
            "unrecognised transcript format: no known parser matches the content",
            warnings,
        )

    # The shareable copy keeps the transcript's own shape: a single document
    # as-is, an array or line records under ``events``. A one-record JSONL
    # file is still line records, not a document.
    whole = load_json_document(text)
    parse_input = text
    if isinstance(whole, dict) and isinstance(whole.get("events"), list):
        # A wrapper object: the records live under ``events``. Parse them as
        # lines; the wrapper itself is the shareable copy.
        parse_input = "\n".join(json.dumps(record) for record in whole["events"])
        transcript = whole
    elif isinstance(whole, list):
        transcript = {"events": whole}
    elif isinstance(whole, dict) and detected not in _LINE_FORMATS:
        transcript = whole
    else:
        transcript = _line_records(text, warnings)

    try:
        events = get_parser(detected).parse(parse_input)
    except Exception as exc:  # noqa: BLE001 - a malformed transcript is data, not a crash
        raise NoParseableEventsError(
            "parse_failed", f"failed to parse as '{detected}': {exc}", warnings
        ) from exc
    return events, detected, transcript, warnings


def _line_records(text: str, warnings: list[str]) -> dict[str, Any]:
    """Collect JSONL records into the shareable ``{"events": [...]}`` shape.

    Lines that are not JSON are named in ``warnings`` (the parsers skip them
    silently). A ``sessionId`` on any record is promoted to ``session_id``.
    """
    events: list[Any] = []
    session_id: str | None = None
    unreadable: list[int] = []
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            unreadable.append(number)
            continue
        events.append(entry)
        if session_id is None and isinstance(entry, dict) and isinstance(entry.get("sessionId"), str):
            session_id = entry["sessionId"]
    for number in unreadable[:_WARNING_DETAIL_LIMIT]:
        warnings.append(f"line {number}: not valid JSON, skipped")
    if len(unreadable) > _WARNING_DETAIL_LIMIT:
        warnings.append(f"{len(unreadable) - _WARNING_DETAIL_LIMIT} more line(s) were not valid JSON, skipped")
    payload: dict[str, Any] = {"events": events}
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


def _events_format(events: list[CanonicalEvent]) -> str:
    for event in events:
        for ref in event.source_refs:
            if ref.get("kind") == "parser" and ref.get("value"):
                return str(ref["value"])
    return "events"


def _event_record(event: CanonicalEvent) -> dict[str, Any]:
    record = {
        "id": str(event.id),
        "session_id": event.session_id,
        "timestamp": event.timestamp.isoformat(),
        "type": event.event_type.value,
        "agent_id": event.agent_id,
        "action": event.action,
        "parent_event_id": str(event.parent_event_id) if event.parent_event_id else None,
        "inputs": event.inputs,
        "outputs": event.outputs,
        "metadata": event.metadata,
    }
    return dict(json.loads(json.dumps(record, default=str)))


def _stabilise_event_ids(events: list[CanonicalEvent], run_id: uuid.UUID) -> None:
    """Derive every event id from the run id so ids survive re-analysis."""
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for index, event in enumerate(events):
        id_map[event.id] = uuid.uuid5(
            run_id, f"{index}:{event.event_type.value}:{event.action}:{event.agent_id}"
        )
    for event in events:
        event.id = id_map[event.id]
        if event.parent_event_id is not None:
            event.parent_event_id = id_map.get(event.parent_event_id)


def _findings(analysis: AnalysisResult) -> list[Finding]:
    findings = [
        Finding(
            kind="risk",
            event_index=index,
            event_id=str(event.id),
            risks=tuple(event.risk_classification.active_flags()),
            summary=event.summary or event.action,
        )
        for index, event in enumerate(analysis.events)
        if event.risk_classification is not None and event.has_risk_flags()
    ]
    node = analysis.inflection_node
    if node is not None and analysis.candidate_break_point is not None:
        findings.append(
            Finding(
                kind="break_point",
                event_index=node.sequence_num,
                event_id=str(node.event.id),
                risks=tuple(node.event.risk_classification.active_flags())
                if node.event.risk_classification
                else (),
                summary=analysis.candidate_break_point.summary,
            )
        )
    return findings


def _signature_hits(match_summary: dict[str, Any]) -> list[SignatureHit]:
    hits: list[SignatureHit] = []
    for raw in match_summary.get("matches") or []:
        signature_id = raw.get("signature_id")
        if not isinstance(signature_id, str) or not signature_id.strip():
            continue
        confidence = _confidence(raw.get("confidence"))
        hits.append(
            SignatureHit(
                signature_id=signature_id.strip(),
                mechanism_id=raw.get("mechanism_id") if isinstance(raw.get("mechanism_id"), str) else None,
                confidence=confidence,
                confidence_band=_confidence_band(confidence),
                summary=raw.get("summary") if isinstance(raw.get("summary"), str) else None,
                event_ids=tuple(ref for ref in raw.get("evidence_refs") or [] if isinstance(ref, str)),
            )
        )
    return hits


def _confidence(value: Any) -> float | None:
    try:
        return None if value is None else min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


def _confidence_band(confidence: float | None) -> str | None:
    """Coarse band a receiving endpoint can group on without the raw float."""
    if confidence is None:
        return None
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    if confidence >= 0.25:
        return "low"
    return "very_low"


# --------------------------------------------------------------------------- #
# submit
# --------------------------------------------------------------------------- #


def submit(
    run: AnalysedRun,
    visibility: str = "community",
    key: str | None = None,
    *,
    source_session_id: str | None = None,
    workflow_reference: str | None = None,
    project_reference: str | None = None,
    source_report_id: str | None = None,
    agent_id: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    environment: str | None = None,
    backfill: bool = False,
    include_analysis: bool = False,
) -> SubmitReceipt:
    """Send a run's redacted transcript to DriftShield.

    ``visibility="community"`` needs no key and feeds the public dataset;
    ``visibility="workspace"`` needs the workspace API ``key``. Both send
    ``run.redacted_transcript``; the raw run never leaves the machine.

    Raises :class:`SubmitError` for a bad visibility, a missing or misplaced
    key, an invalid option, missing intake configuration or a transport
    failure.
    """
    resolved = _VISIBILITY_ALIASES.get(visibility.strip().lower())
    if resolved is None:
        raise SubmitError("visibility must be 'community' or 'workspace'.")
    if resolved == "workspace" and not key:
        raise SubmitError("visibility 'workspace' requires an API key.")
    if resolved == "community" and key:
        raise SubmitError("visibility 'community' takes no API key; it is the keyless public lane.")
    if backfill and resolved != "workspace":
        raise SubmitError(
            "backfill requires visibility 'workspace' (the authenticated lane); "
            "the community lane does not accept a backfill declaration."
        )
    if environment is not None:
        environment = environment.strip().lower()
        if environment not in DECLARED_ENVIRONMENTS:
            raise SubmitError(f"environment must be one of: {', '.join(sorted(DECLARED_ENVIRONMENTS))}.")

    config = TelemetryService().load_config()
    if resolved == "community":
        intake_url = effective_oss_intake_url(config)
        if intake_url is None:
            raise SubmitError(
                "Remote submission is disabled (`telemetry remote-disable`). "
                "Run `driftshield telemetry remote-enable --intake-url URL` to re-enable."
            )
    else:
        intake_url = config.remote_intake_url
        if intake_url is None:
            raise SubmitError(
                "Remote submission is not configured. Run `driftshield telemetry "
                "remote-enable --intake-url URL` first."
            )

    if workflow_reference is None:
        declared = run.transcript.get("workflow_reference")
        workflow_reference = declared if isinstance(declared, str) and declared.strip() else None
    workflow_reference = workflow_reference or DEFAULT_WORKFLOW_REFERENCE

    derived = _openclaw_provenance(run)
    agent_id = agent_id or derived.get("agent_id")
    model_name = model_name or derived.get("model_name")

    file_name = Path(run.source).name if run.source else f"{run.run_id}.json"
    source_session_id = source_session_id or (Path(run.source).stem if run.source else str(run.run_id))
    session_observed_at = run.session_observed_at.isoformat()
    summary = run.signature_summary if include_analysis else None

    # Submitting is the production declaration on both lanes. The environment
    # key rides the shareable copy untouched by redaction, so stamping it here
    # is the same as stamping it before.
    payload = dict(run.redacted_transcript)
    metadata = dict(payload["metadata"]) if isinstance(payload.get("metadata"), dict) else {}
    if environment is not None:
        metadata[_ENVIRONMENT_KEY] = environment
    else:
        metadata.setdefault(_ENVIRONMENT_KEY, EnvironmentClass.PRODUCTION.value)
    payload["metadata"] = metadata

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    provenance: dict[str, object] = {"source_session_id": source_session_id}
    for name, value in (
        ("project_reference", project_reference),
        ("source_report_id", source_report_id),
        ("agent_id", agent_id),
        ("model_name", model_name),
        ("model_version", model_version),
        ("session_observed_at", session_observed_at),
    ):
        if value is not None:
            provenance[name] = value
    if summary is not None:
        provenance["signature_summary"] = summary.model_dump(mode="json")

    if resolved == "workspace":
        assert key is not None
        teams_kwargs: dict[str, Any] = {"backfill": True} if backfill else {}
        result = submit_teams_via_presigned_upload(
            config=TeamsUploadConfig(intake_url=intake_url, api_key=key),
            payload=payload,
            workflow_reference=workflow_reference,
            file_name=file_name,
            provenance=provenance,
            **teams_kwargs,
        )
    elif len(encoded.encode("utf-8")) > INLINE_PAYLOAD_THRESHOLD_BYTES:
        result = submit_oss_via_presigned_upload(
            config=OssUploadConfig(intake_url=intake_url),
            payload=payload,
            workflow_reference=workflow_reference,
            file_name=file_name,
            provenance=provenance,
        )
    else:
        submission = build_oss_submission_request(
            source_session_id=source_session_id,
            redacted_payload=payload,
            workflow_reference=workflow_reference,
            project_reference=project_reference,
            source_report_id=source_report_id,
            agent_id=agent_id,
            model_name=model_name,
            model_version=model_version,
            session_observed_at=session_observed_at,
            signature_summary=summary,
        )
        result = post_oss_submission(
            config=OssRemoteSubmissionConfig(intake_url=intake_url), submission=submission
        )

    deprecation_warning: str | None = None
    if (
        result.server_contract_version is not None
        and result.server_contract_version != SUPPORTED_CONTRACT_VERSION
    ):
        deprecation_warning = (
            f"intake server advertises {result.server_contract_version}; this client is on "
            f"{SUPPORTED_CONTRACT_VERSION}. The server is in its post-bump deprecation window: "
            "submissions are still accepted, but the server operator should upgrade before "
            "the window closes."
        )
    return SubmitReceipt(
        submission_id=result.response.submission_id,
        processing_status=result.response.processing_status,
        visibility=resolved,
        server_contract_version=result.server_contract_version,
        deprecation_warning=deprecation_warning,
    )


def _openclaw_provenance(run: AnalysedRun) -> dict[str, str]:
    """Agent and model provenance an OpenClaw trajectory carries on its records."""
    if run.detected_format != "openclaw_trajectory":
        return {}
    records = run.transcript.get("events")
    if not isinstance(records, list):
        return {}
    agent_suffix = provider = model_id = None
    for record in records:
        if not isinstance(record, dict):
            continue
        provider = provider or (record.get("provider") if isinstance(record.get("provider"), str) else None)
        model_id = model_id or (record.get("modelId") if isinstance(record.get("modelId"), str) else None)
        data = record.get("data")
        if agent_suffix is None and isinstance(data, dict) and isinstance(data.get("agentId"), str):
            agent_suffix = data["agentId"]
        if provider and model_id and agent_suffix:
            break
    provenance = {"agent_id": "openclaw" if agent_suffix is None else f"openclaw:{agent_suffix}"}
    if model_id is not None:
        provenance["model_name"] = model_id if provider is None else f"{provider}/{model_id}"
    return provenance


def workspace_key_from_environment() -> str | None:
    """The workspace API key the CLI reads from the environment."""
    return os.environ.get("DRIFTSHIELD_API_KEY") or os.environ.get("API_KEY") or None


__all__ = [
    "AnalysedRun",
    "Finding",
    "NoParseableEventsError",
    "SignatureHit",
    "SubmitError",
    "SubmitReceipt",
    "UnsupportedFormatError",
    "analyse_run",
    "submit",
]
