"""Intake submission contract (OSS side).

Pydantic models for the request body that ``driftshield submit-session``
sends to the configured intake server. The server validates the same
shape and rejects with HTTP 422 when ``envelope_contract_version`` or
``schema_version`` are not in ``ACCEPTED_CONTRACT_VERSIONS``. Keep
``SUPPORTED_CONTRACT_VERSION`` and the model field sets in lockstep with
the server-side contract; both ends must continue to advertise the same
``SUPPORTED_CONTRACT_VERSION`` outside the post-bump deprecation window.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SUPPORTED_CONTRACT_VERSION = "phase3g.v1"
# Intake servers accept submissions on either pin during a 90-day
# deprecation window after a contract bump, so older clients can still
# submit while operators upgrade. The OSS-side declaration is here for
# contract-pin parity with the server validator; this module has no
# accept-logic of its own.
ACCEPTED_CONTRACT_VERSIONS: frozenset[str] = frozenset({"phase3f.v1", "phase3g.v1"})
MAX_ENVELOPE_BYTES = 256_000
REDACTION_MANIFEST_VERSION_V1 = "redaction-manifest.v1"
REDACTION_MANIFEST_VERSION_V2 = "redaction-manifest.v2"
# Current OSS builders emit v2 manifests. Server side accepts both v1 and v2
# during the deprecation window: ship manifest provenance fields without
# waiting on an unrelated envelope-bump release.
REDACTION_MANIFEST_VERSION = REDACTION_MANIFEST_VERSION_V2
ACCEPTED_REDACTION_MANIFEST_VERSIONS: frozenset[str] = frozenset(
    {REDACTION_MANIFEST_VERSION_V1, REDACTION_MANIFEST_VERSION_V2}
)
REQUIRED_REDACTION_FIELDS: frozenset[str] = frozenset(
    {"prompts", "responses", "user_identifiers"}
)


class RedactionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(default=REDACTION_MANIFEST_VERSION)
    redaction_applied: bool
    redacted_fields: list[str] = Field(min_length=1)
    redactor_version: str | None = Field(default=None, min_length=1)
    redaction_ruleset_version: str | None = Field(default=None, min_length=1)


class ConsentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_version: str = Field(min_length=1)
    consent_granted: bool
    captured_at: datetime
    revoked_at: datetime | None = None


DEFAULT_WORKFLOW_REFERENCE = "default"


class SubmissionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(min_length=1)
    source_session_id: str = Field(min_length=1)
    source_report_id: str | None = None
    workflow_reference: str = Field(default=DEFAULT_WORKFLOW_REFERENCE, min_length=1)
    project_reference: str | None = Field(default=None, min_length=1)
    schema_version: str = Field(min_length=1)
    payload: dict[str, Any]
    payload_size_bytes: int = Field(ge=1, le=MAX_ENVELOPE_BYTES)
    redaction_manifest: RedactionManifest
    agent_id: str | None = Field(default=None, min_length=1)
    model_name: str | None = Field(default=None, min_length=1)
    model_version: str | None = Field(default=None, min_length=1)


class IntakeSubmissionRequest(BaseModel):
    """Authenticated POST /v1/intake request body.

    Kept here for contract-pin reasons (mirrors intel-side authenticated path).
    The OSS CLI does NOT use this shape; OSS uses OssSubmissionRequest.
    """

    model_config = ConfigDict(extra="forbid")

    installation_id: str = Field(min_length=1)
    envelope_contract_version: str = Field(min_length=1)
    consent_state: ConsentState
    envelope: SubmissionEnvelope


class OssSubmissionRequest(BaseModel):
    """Unauthenticated POST /v1/oss/submissions request body (D19).

    No installation_id, no consent_state. The server binds the persisted row
    to the in-stack OSS fallback installation + consent. The client never
    sees these identifiers.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_contract_version: str = Field(min_length=1)
    envelope: SubmissionEnvelope


class IntakeSubmissionResponse(BaseModel):
    submission_id: str
    processing_status: str
