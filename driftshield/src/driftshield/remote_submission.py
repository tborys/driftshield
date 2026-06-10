"""OSS-side submission envelope builder, redaction, and unauthenticated POST.

OSS submissions go on a dedicated unauthenticated lane. No installation_id, no
api_key header, no consent_state echo. The server binds the persisted row to the
built-in OSS fallback installation and consent record.

The redactor is a recursive ruleset implemented in
:mod:`driftshield.recursive_redactor`. The public manifest contract advertises
``REQUIRED_REDACTION_FIELDS``; the recursive ruleset (tool-IO keys, regex
secrets, path-shape, email) is an implementation detail behind that contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request

from driftshield.intake_contract import (
    DEFAULT_WORKFLOW_REFERENCE,
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    IntakeSubmissionResponse,
    OssSubmissionRequest,
    RedactionManifest,
    SignatureSummary,
    SubmissionEnvelope,
)
from driftshield.recursive_redactor import (
    REDACTION_RULESET_VERSION,
    REDACTOR_VERSION,
    RedactionResult,
    redact,
)


SERVER_CONTRACT_VERSION_HEADER = "X-DriftShield-Contract-Version"

# Known submit suffixes a configured (or baked) intake URL may carry. Routes
# are derived from the base so one canonical intake URL serves every lane.
_OSS_SUBMIT_SUFFIXES = ("/v1/intake", "/v1/oss/submissions")

# The live route for the unauthenticated inline OSS submission. POSTing the
# inline body to /v1/intake instead hits the authenticated intake route and
# fails with 422 missing installation_id.
OSS_INLINE_SUBMIT_PATH = "/v1/oss/submissions"


def derive_intake_base_url(intake_url: str) -> str:
    """Strip the known submit suffix from a configured intake URL.

    The configured ``remote_intake_url`` ends with ``/v1/intake`` or
    ``/v1/oss/submissions``; strip it so per-lane paths can be appended to
    the same host without double-pathing.
    """
    trimmed = intake_url.rstrip("/")
    for suffix in _OSS_SUBMIT_SUFFIXES:
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
    return trimmed


def derive_oss_inline_submit_url(intake_url: str) -> str:
    """Resolve the inline OSS submission endpoint from any intake URL shape.

    Idempotent for URLs already ending in ``/v1/oss/submissions``.
    """
    return derive_intake_base_url(intake_url) + OSS_INLINE_SUBMIT_PATH


_DEFAULT_SOURCE_SYSTEM = "driftshield-oss"


# Top-level key hints for the shapes recognisable from the payload's key-set
# alone. The two events-carrying shapes (openclaw_trajectory and claude_code)
# are NOT in this table: both arrive as a ``payload["events"]`` list, so they
# are told apart by probing the event records themselves in
# :func:`detect_shape`.
_KNOWN_SHAPE_HINTS: dict[str, frozenset[str]] = {
    "claude_desktop": frozenset({"conversation", "messages"}),
    "codex": frozenset({"session", "turns"}),
    "openai_chat": frozenset({"choices", "model"}),
    "langchain": frozenset({"runs", "trace"}),
    "crewai": frozenset({"crew", "tasks"}),
    "generic_session": frozenset({"session_id"}),
}

# OpenClaw runtime trajectory events carry this envelope on every record
# (run/trace correlation + schema version), which native Claude Code JSONL
# lines never do. Probed before the claude_code fallback so OpenClaw
# trajectories stop mislabelling as claude_code.
_OPENCLAW_EVENT_KEYS: frozenset[str] = frozenset(
    {"runId", "traceId", "schemaVersion", "seq", "source"}
)


def _looks_like_openclaw_trajectory(events: Any) -> bool:
    if not isinstance(events, list) or len(events) == 0:
        return False
    probed = [event for event in events[:8] if isinstance(event, dict)]
    if len(probed) == 0:
        return False
    return all(_OPENCLAW_EVENT_KEYS.issubset(event.keys()) for event in probed)


def _looks_like_claude_code_events(events: Any) -> bool:
    # Native Claude Code JSONL lines all carry a string ``type``
    # discriminator (user / assistant / summary / system). Requiring it
    # stops arbitrary line-delimited JSON from waving through the
    # unknown-shape redaction guard as claude_code.
    if not isinstance(events, list) or len(events) == 0:
        return False
    return any(
        isinstance(event, dict) and isinstance(event.get("type"), str)
        for event in events
    )


class UnknownTranscriptShapeError(ValueError):
    """Raised when the input transcript does not match a known shape.

    Silent under-redaction on unrecognised shapes is the failure mode
    driftshield#109 exists to close. The caller must either map the payload
    into a known shape or pass ``force_unknown_shape=True`` to override.
    """


@dataclass(frozen=True, slots=True)
class OssRemoteSubmissionConfig:
    """Minimal config for the unauthenticated OSS submission lane."""

    intake_url: str


class RemoteSubmissionError(RuntimeError):
    """Raised when the remote submission cannot be assembled or accepted."""


def detect_shape(payload: dict[str, Any]) -> str | None:
    """Return the matching known-shape name or ``None`` if unrecognised.

    Detection is best-effort and heuristic. It exists so the CLI can refuse
    to submit payloads the recursive redactor was not designed against,
    rather than silently under-redacting them.

    Events-carrying payloads are content-probed: OpenClaw runtime
    trajectories detect as ``openclaw_trajectory``, native Claude Code
    lines as ``claude_code``. An events list matching neither probe is not
    claude_code; it falls to the key-hint table (and then to unknown).
    """
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if isinstance(events, list) and len(events) > 0:
        if _looks_like_openclaw_trajectory(events):
            return "openclaw_trajectory"
        if _looks_like_claude_code_events(events):
            return "claude_code"
    keys = set(payload.keys())
    for shape, required in _KNOWN_SHAPE_HINTS.items():
        if required.issubset(keys):
            return shape
    return None


def derive_openclaw_provenance(payload: dict[str, Any]) -> dict[str, str]:
    """Best-effort real provenance from an OpenClaw trajectory payload.

    OpenClaw trajectory events carry the driving provider/model
    (``provider`` / ``modelId``) and the agent name
    (``data.agentId``) on the runtime records. Returns ``agent_id`` /
    ``model_name`` values for the envelope, or an empty dict when the
    payload is not an OpenClaw trajectory. Callers apply explicit flags
    first; this only fills gaps.
    """
    events = payload.get("events")
    if not _looks_like_openclaw_trajectory(events):
        return {}
    agent_suffix: str | None = None
    provider: str | None = None
    model_id: str | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if provider is None and isinstance(event.get("provider"), str):
            provider = event["provider"]
        if model_id is None and isinstance(event.get("modelId"), str):
            model_id = event["modelId"]
        data = event.get("data")
        if (
            agent_suffix is None
            and isinstance(data, dict)
            and isinstance(data.get("agentId"), str)
        ):
            agent_suffix = data["agentId"]
        if provider is not None and model_id is not None and agent_suffix is not None:
            break
    provenance: dict[str, str] = {
        "agent_id": "openclaw" if agent_suffix is None else f"openclaw:{agent_suffix}",
    }
    if model_id is not None:
        provenance["model_name"] = (
            model_id if provider is None else f"{provider}/{model_id}"
        )
    return provenance


def redact_payload_with_manifest(payload: dict[str, Any]) -> RedactionResult:
    """Recursive redaction returning the rewritten payload + redaction entries.

    Consumed by ``--show-manifest`` and ``--dry-run-redaction`` in the CLI so
    callers can inspect what the redactor stripped without submitting.
    """
    return redact(payload)


def redact_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Recursively strip sensitive content from the payload.

    Returns ``(redacted_payload, redacted_fields)``. The advertised
    ``redacted_fields`` list is the public ``REQUIRED_REDACTION_FIELDS``
    superset so the intel-side validator (``incomplete_redaction_manifest``)
    stays satisfied. The deeper v2 ruleset is implementation-only.
    """
    result = redact_payload_with_manifest(payload)
    redacted_payload = result.payload
    if not isinstance(redacted_payload, dict):
        raise RemoteSubmissionError(
            "redacted payload must remain a JSON object at top level"
        )
    return redacted_payload, sorted(REQUIRED_REDACTION_FIELDS)


def _encode_payload(payload: dict[str, Any]) -> tuple[bytes, int]:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return encoded, len(encoded)


def build_oss_submission_request(
    *,
    source_session_id: str,
    payload: dict[str, Any],
    source_system: str = _DEFAULT_SOURCE_SYSTEM,
    workflow_reference: str | None = None,
    project_reference: str | None = None,
    source_report_id: str | None = None,
    force_unknown_shape: bool = False,
    agent_id: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    signature_summary: SignatureSummary | None = None,
) -> OssSubmissionRequest:
    """Build an unauthenticated OSS submission request.

    ``force_unknown_shape`` defaults to False. The recursive redactor was
    designed against the known transcript shapes (the key-hint shapes in
    :data:`_KNOWN_SHAPE_HINTS` plus the two events-probed shapes,
    openclaw_trajectory and claude_code); an unrecognised shape raises
    :class:`UnknownTranscriptShapeError` unless the caller passes
    ``force_unknown_shape=True``.

    No installation_id, no consent_state. The envelope still carries
    redaction_manifest + payload_size_bytes + schema_version, all enforced
    server-side by OssSubmissionService.
    """
    shape = detect_shape(payload)
    if shape is None and not force_unknown_shape:
        raise UnknownTranscriptShapeError(
            "Unrecognised transcript shape. Map the payload into a known "
            "shape or pass force_unknown_shape=True (CLI: "
            "--force-unknown-shape) to override."
        )

    redacted_payload, redacted_fields = redact_payload(payload)
    _, payload_size = _encode_payload(redacted_payload)

    envelope_workflow_reference = (
        workflow_reference if workflow_reference is not None else DEFAULT_WORKFLOW_REFERENCE
    )
    envelope = SubmissionEnvelope(
        source_system=source_system,
        source_session_id=source_session_id,
        source_report_id=source_report_id,
        workflow_reference=envelope_workflow_reference,
        project_reference=project_reference,
        schema_version=SUPPORTED_CONTRACT_VERSION,
        payload=redacted_payload,
        payload_size_bytes=payload_size,
        redaction_manifest=RedactionManifest(
            manifest_version=REDACTION_MANIFEST_VERSION,
            redaction_applied=True,
            redacted_fields=redacted_fields,
            redactor_version=REDACTOR_VERSION,
            redaction_ruleset_version=REDACTION_RULESET_VERSION,
        ),
        agent_id=agent_id,
        model_name=model_name,
        model_version=model_version,
        signature_summary=signature_summary,
    )
    return OssSubmissionRequest(
        envelope_contract_version=SUPPORTED_CONTRACT_VERSION,
        envelope=envelope,
    )


def build_redacted_payload(
    *,
    payload: dict[str, Any],
    force_unknown_shape: bool = False,
) -> dict[str, Any]:
    """Redact a transcript payload without wrapping it in the envelope model.

    The :class:`SubmissionEnvelope` model caps ``payload_size_bytes`` at
    256 KB, which is exactly the limit large transcripts exceed. The
    presigned-S3 upload lane sends the redacted payload as an object, not
    inline in that model, so it needs the redacted dict without the cap.
    Shape detection + the recursive redactor are identical to
    :func:`build_oss_submission_request`.
    """
    shape = detect_shape(payload)
    if shape is None and not force_unknown_shape:
        raise UnknownTranscriptShapeError(
            "Unrecognised transcript shape. Map the payload into a known "
            "shape or pass force_unknown_shape=True (CLI: "
            "--force-unknown-shape) to override."
        )
    redacted_payload, _ = redact_payload(payload)
    return redacted_payload


@dataclass(frozen=True, slots=True)
class OssSubmissionResult:
    """Response + transport-level metadata for one OSS submission.

    ``server_contract_version`` is the value of the
    ``X-DriftShield-Contract-Version`` response header, or ``None`` if the
    server did not advertise one. Callers compare it against
    :data:`driftshield.intake_contract.SUPPORTED_CONTRACT_VERSION` to detect
    a deprecated server.
    """

    response: IntakeSubmissionResponse
    server_contract_version: str | None


def post_oss_submission(
    *,
    config: OssRemoteSubmissionConfig,
    submission: OssSubmissionRequest,
    opener: Any = None,
) -> OssSubmissionResult:
    """Single unauthenticated POST to /v1/oss/submissions. No retry on failure.

    No X-API-Key header. No Authorization header. The endpoint is derived
    from ``config.intake_url`` (a ``/v1/intake`` or ``/v1/oss/submissions``
    suffix is normalised to the inline OSS route), so the canonical
    community intake URL works for the inline lane too.
    """
    body = submission.model_dump_json().encode("utf-8")
    req = request.Request(
        derive_oss_inline_submit_url(config.intake_url),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    urlopen = opener or request.urlopen
    try:
        with urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            server_contract_version = resp.headers.get(SERVER_CONTRACT_VERSION_HEADER)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RemoteSubmissionError(f"intake HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RemoteSubmissionError(f"intake unreachable: {exc.reason}") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RemoteSubmissionError(f"intake returned non-JSON body: {raw!r}") from exc
    response = IntakeSubmissionResponse.model_validate(decoded)
    return OssSubmissionResult(
        response=response,
        server_contract_version=server_contract_version,
    )


__all__ = [
    "REDACTION_RULESET_VERSION",
    "REDACTOR_VERSION",
    "SERVER_CONTRACT_VERSION_HEADER",
    "OssRemoteSubmissionConfig",
    "OssSubmissionResult",
    "RemoteSubmissionError",
    "UnknownTranscriptShapeError",
    "build_oss_submission_request",
    "build_redacted_payload",
    "derive_intake_base_url",
    "derive_openclaw_provenance",
    "derive_oss_inline_submit_url",
    "detect_shape",
    "post_oss_submission",
    "redact_payload",
    "redact_payload_with_manifest",
]
