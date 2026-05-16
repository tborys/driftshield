"""Phase 3h intake submission contract (OSS side).

Duplicate-with-version-pin of the canonical models at
driftshield-intel/src/driftshield_intel/intake_api.py:35-80.
Promote to a shared package in Phase 3i. Until then, any change here must be
mirrored on the intel side and vice versa, and both ends must continue to
advertise the same SUPPORTED_CONTRACT_VERSION.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SUPPORTED_CONTRACT_VERSION = "phase3f.v1"
MAX_ENVELOPE_BYTES = 256_000
REDACTION_MANIFEST_VERSION = "redaction-manifest.v1"
REQUIRED_REDACTION_FIELDS: frozenset[str] = frozenset(
    {"prompts", "responses", "user_identifiers"}
)


class RedactionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(default=REDACTION_MANIFEST_VERSION)
    redaction_applied: bool
    redacted_fields: list[str] = Field(min_length=1)


class ConsentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_version: str = Field(min_length=1)
    consent_granted: bool
    captured_at: datetime
    revoked_at: datetime | None = None


class SubmissionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(min_length=1)
    source_session_id: str = Field(min_length=1)
    source_report_id: str | None = None
    workflow_reference: str | None = Field(default=None, min_length=1)
    project_reference: str | None = Field(default=None, min_length=1)
    schema_version: str = Field(min_length=1)
    payload: dict[str, Any]
    payload_size_bytes: int = Field(ge=1, le=MAX_ENVELOPE_BYTES)
    redaction_manifest: RedactionManifest


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
