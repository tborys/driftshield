"""OSS-side submission envelope builder, redaction, and unauthenticated POST.

Per Phase 3h D19 (operator decision 2026-05-16): OSS submissions go on a
dedicated unauthenticated lane. No installation_id, no api_key header, no
consent_state echo. The server binds the persisted row to the in-stack OSS
fallback installation + consent.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request

from driftshield.intake_contract import (
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    IntakeSubmissionResponse,
    OssSubmissionRequest,
    RedactionManifest,
    SubmissionEnvelope,
)


_DEFAULT_SOURCE_SYSTEM = "driftshield-oss"


@dataclass(frozen=True, slots=True)
class OssRemoteSubmissionConfig:
    """Minimal config for the unauthenticated OSS submission lane."""

    intake_url: str


class RemoteSubmissionError(RuntimeError):
    """Raised when the remote submission cannot be assembled or accepted."""


def redact_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Strip required-redaction fields from the top level of the payload.

    Returns (redacted_payload, redacted_fields). The manifest must always
    advertise the full REQUIRED_REDACTION_FIELDS superset, even if the input
    payload did not carry one of them, so the intake validator
    (incomplete_redaction_manifest) is satisfied without lying about it.
    """
    redacted = {k: v for k, v in payload.items() if k not in REQUIRED_REDACTION_FIELDS}
    return redacted, sorted(REQUIRED_REDACTION_FIELDS)


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
) -> OssSubmissionRequest:
    """Build an unauthenticated OSS submission request.

    No installation_id, no consent_state. The envelope still carries
    redaction_manifest + payload_size_bytes + schema_version, all enforced
    server-side by OssSubmissionService.
    """
    redacted_payload, redacted_fields = redact_payload(payload)
    _, payload_size = _encode_payload(redacted_payload)

    envelope = SubmissionEnvelope(
        source_system=source_system,
        source_session_id=source_session_id,
        source_report_id=source_report_id,
        workflow_reference=workflow_reference,
        project_reference=project_reference,
        schema_version=SUPPORTED_CONTRACT_VERSION,
        payload=redacted_payload,
        payload_size_bytes=payload_size,
        redaction_manifest=RedactionManifest(
            manifest_version=REDACTION_MANIFEST_VERSION,
            redaction_applied=True,
            redacted_fields=redacted_fields,
        ),
    )
    return OssSubmissionRequest(
        envelope_contract_version=SUPPORTED_CONTRACT_VERSION,
        envelope=envelope,
    )


def post_oss_submission(
    *,
    config: OssRemoteSubmissionConfig,
    submission: OssSubmissionRequest,
    opener: Any = None,
) -> IntakeSubmissionResponse:
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
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RemoteSubmissionError(f"intake HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RemoteSubmissionError(f"intake unreachable: {exc.reason}") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RemoteSubmissionError(f"intake returned non-JSON body: {raw!r}") from exc
    return IntakeSubmissionResponse.model_validate(decoded)
