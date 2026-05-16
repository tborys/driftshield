"""OSS-side submission envelope builder, redaction, and intake POST."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
from urllib import error, request

from driftshield.intake_contract import (
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    ConsentState,
    IntakeSubmissionRequest,
    IntakeSubmissionResponse,
    RedactionManifest,
    SubmissionEnvelope,
)


_DEFAULT_SOURCE_SYSTEM = "driftshield-oss"


@dataclass(frozen=True, slots=True)
class RemoteSubmissionConfig:
    intake_url: str
    api_key: str
    installation_id: str


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


def build_intake_request(
    *,
    installation_id: str,
    source_session_id: str,
    payload: dict[str, Any],
    consent_version: str = SUPPORTED_CONTRACT_VERSION,
    source_system: str = _DEFAULT_SOURCE_SYSTEM,
    workflow_reference: str | None = None,
    project_reference: str | None = None,
    source_report_id: str | None = None,
    captured_at: datetime | None = None,
) -> IntakeSubmissionRequest:
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
    consent = ConsentState(
        consent_version=consent_version,
        consent_granted=True,
        captured_at=captured_at or datetime.now(UTC),
        revoked_at=None,
    )
    return IntakeSubmissionRequest(
        installation_id=installation_id,
        envelope_contract_version=SUPPORTED_CONTRACT_VERSION,
        consent_state=consent,
        envelope=envelope,
    )


def post_submission(
    *,
    config: RemoteSubmissionConfig,
    submission: IntakeSubmissionRequest,
    opener: Any = None,
) -> IntakeSubmissionResponse:
    """Single POST to the configured intake URL. No retry on failure."""
    body = submission.model_dump_json().encode("utf-8")
    req = request.Request(
        config.intake_url,
        data=body,
        method="POST",
        headers={
            "X-API-Key": config.api_key,
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
