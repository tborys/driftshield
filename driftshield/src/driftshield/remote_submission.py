"""OSS-side submission envelope builder and unauthenticated POST (internal).

OSS submissions go on a dedicated unauthenticated lane. No installation_id, no
api_key header, no consent_state echo. The server binds the persisted row to the
built-in OSS fallback installation and consent record. Redaction happens before
this module is reached: :func:`driftshield.public.submit` hands over the run's
redacted transcript and the manifest advertises ``REQUIRED_REDACTION_FIELDS``.
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
from driftshield.recursive_redactor import REDACTION_RULESET_VERSION, REDACTOR_VERSION


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


@dataclass(frozen=True, slots=True)
class OssRemoteSubmissionConfig:
    """Minimal config for the unauthenticated OSS submission lane."""

    intake_url: str


class RemoteSubmissionError(RuntimeError):
    """Raised when the remote submission cannot be assembled or accepted."""


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
    redacted_payload: dict[str, Any],
    source_system: str = _DEFAULT_SOURCE_SYSTEM,
    workflow_reference: str | None = None,
    project_reference: str | None = None,
    source_report_id: str | None = None,
    agent_id: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    session_observed_at: str | None = None,
    signature_summary: SignatureSummary | None = None,
) -> OssSubmissionRequest:
    """Build an unauthenticated OSS submission request around an already
    redacted payload (:func:`driftshield.public.submit` is the only caller).

    No installation_id, no consent_state. The envelope still carries
    redaction_manifest + payload_size_bytes + schema_version, all enforced
    server-side. ``session_observed_at`` is the session's own end timestamp
    (ISO 8601 UTC), not ingest time (driftshield#174).
    """
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
            redacted_fields=sorted(REQUIRED_REDACTION_FIELDS),
            redactor_version=REDACTOR_VERSION,
            redaction_ruleset_version=REDACTION_RULESET_VERSION,
        ),
        agent_id=agent_id,
        model_name=model_name,
        model_version=model_version,
        session_observed_at=session_observed_at,
        signature_summary=signature_summary,
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
    "build_oss_submission_request",
    "derive_intake_base_url",
    "derive_oss_inline_submit_url",
    "post_oss_submission",
]
