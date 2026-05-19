"""OSS-side submission envelope builder, redaction, and unauthenticated POST.

Per Phase 3h D19 (operator decision 2026-05-16): OSS submissions go on a
dedicated unauthenticated lane. No installation_id, no api_key header, no
consent_state echo. The server binds the persisted row to the in-stack OSS
fallback installation + consent.

Phase 3i (driftshield#109) replaces the v1 field-name-only redactor with a
recursive ruleset implemented in :mod:`driftshield.recursive_redactor`. The
public manifest contract still advertises ``REQUIRED_REDACTION_FIELDS``; the
internal v2 ruleset (tool-IO keys, regex secrets, path-shape, email) is
implementation-only.
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
    SubmissionEnvelope,
)
from driftshield.recursive_redactor import (
    REDACTION_RULESET_VERSION,
    REDACTOR_VERSION,
    RedactionResult,
    redact,
)


SERVER_CONTRACT_VERSION_HEADER = "X-DriftShield-Contract-Version"


_DEFAULT_SOURCE_SYSTEM = "driftshield-oss"


_KNOWN_SHAPE_HINTS: dict[str, frozenset[str]] = {
    "claude_code": frozenset({"events"}),
    "claude_desktop": frozenset({"conversation", "messages"}),
    "codex": frozenset({"session", "turns"}),
    "openai_chat": frozenset({"choices", "model"}),
    "langchain": frozenset({"runs", "trace"}),
    "crewai": frozenset({"crew", "tasks"}),
    "generic_session": frozenset({"session_id"}),
}


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
    """
    if not isinstance(payload, dict):
        return None
    keys = set(payload.keys())
    for shape, required in _KNOWN_SHAPE_HINTS.items():
        if required.issubset(keys):
            return shape
    return None


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
) -> OssSubmissionRequest:
    """Build an unauthenticated OSS submission request.

    ``force_unknown_shape`` defaults to False. The recursive redactor was
    designed against the six known transcript shapes listed in
    :data:`_KNOWN_SHAPE_HINTS`; an unrecognised top-level shape raises
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
    )
    return OssSubmissionRequest(
        envelope_contract_version=SUPPORTED_CONTRACT_VERSION,
        envelope=envelope,
    )


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

    No X-API-Key header. No Authorization header. The intake URL is taken
    verbatim from TelemetryConfig.remote_intake_url.
    """
    body = submission.model_dump_json().encode("utf-8")
    req = request.Request(
        config.intake_url,
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
    "detect_shape",
    "post_oss_submission",
    "redact_payload",
    "redact_payload_with_manifest",
]
