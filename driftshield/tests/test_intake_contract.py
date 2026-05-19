"""Structural pin for the duplicated phase3g.v1 intake contract.

Until the contract is promoted to a shared package (Phase 3i+), this test
locks the OSS-side models against a hardcoded reference snapshot copied
from `driftshield-intel/src/driftshield_intel/intake_api.py:57-149`.

If the canonical intel models change, update both the reference snapshot
below AND `src/driftshield/intake_contract.py`, in lockstep. Otherwise the
intake validator will reject submissions silently or with a misleading
error code.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from driftshield.intake_contract import (
    ACCEPTED_CONTRACT_VERSIONS,
    DEFAULT_WORKFLOW_REFERENCE,
    MAX_ENVELOPE_BYTES,
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    ConsentState,
    IntakeSubmissionRequest,
    OssSubmissionRequest,
    RedactionManifest,
    SubmissionEnvelope,
)


# Reference snapshot — keep in sync with intake_api.py:57-149.
_REFERENCE_CONSTANTS = {
    "SUPPORTED_CONTRACT_VERSION": "phase3g.v1",
    "ACCEPTED_CONTRACT_VERSIONS": frozenset({"phase3f.v1", "phase3g.v1"}),
    "DEFAULT_WORKFLOW_REFERENCE": "default",
    "MAX_ENVELOPE_BYTES": 256_000,
    "REDACTION_MANIFEST_VERSION": "redaction-manifest.v2",
    "REQUIRED_REDACTION_FIELDS": frozenset({"prompts", "responses", "user_identifiers"}),
}

_REFERENCE_FIELDS = {
    "RedactionManifest": {
        "manifest_version",
        "redaction_applied",
        "redacted_fields",
        "redactor_version",
        "redaction_ruleset_version",
    },
    "ConsentState": {
        "consent_version",
        "consent_granted",
        "captured_at",
        "revoked_at",
    },
    "SubmissionEnvelope": {
        "source_system",
        "source_session_id",
        "source_report_id",
        "workflow_reference",
        "project_reference",
        "schema_version",
        "payload",
        "payload_size_bytes",
        "redaction_manifest",
        "agent_id",
        "model_name",
        "model_version",
    },
    "IntakeSubmissionRequest": {
        "installation_id",
        "envelope_contract_version",
        "consent_state",
        "envelope",
    },
    # D19: OSS unauthenticated submission request. No installation_id, no consent_state.
    "OssSubmissionRequest": {
        "envelope_contract_version",
        "envelope",
    },
}


def test_contract_constants_match_canonical_snapshot():
    assert SUPPORTED_CONTRACT_VERSION == _REFERENCE_CONSTANTS["SUPPORTED_CONTRACT_VERSION"]
    assert ACCEPTED_CONTRACT_VERSIONS == _REFERENCE_CONSTANTS["ACCEPTED_CONTRACT_VERSIONS"]
    assert DEFAULT_WORKFLOW_REFERENCE == _REFERENCE_CONSTANTS["DEFAULT_WORKFLOW_REFERENCE"]
    assert MAX_ENVELOPE_BYTES == _REFERENCE_CONSTANTS["MAX_ENVELOPE_BYTES"]
    assert REDACTION_MANIFEST_VERSION == _REFERENCE_CONSTANTS["REDACTION_MANIFEST_VERSION"]
    assert REQUIRED_REDACTION_FIELDS == _REFERENCE_CONSTANTS["REQUIRED_REDACTION_FIELDS"]


def test_accepted_contract_versions_includes_supported_and_predecessor():
    assert SUPPORTED_CONTRACT_VERSION in ACCEPTED_CONTRACT_VERSIONS
    assert "phase3f.v1" in ACCEPTED_CONTRACT_VERSIONS


@pytest.mark.parametrize(
    "model, expected_fields",
    [
        (RedactionManifest, _REFERENCE_FIELDS["RedactionManifest"]),
        (ConsentState, _REFERENCE_FIELDS["ConsentState"]),
        (SubmissionEnvelope, _REFERENCE_FIELDS["SubmissionEnvelope"]),
        (IntakeSubmissionRequest, _REFERENCE_FIELDS["IntakeSubmissionRequest"]),
        (OssSubmissionRequest, _REFERENCE_FIELDS["OssSubmissionRequest"]),
    ],
)
def test_contract_field_set_matches_canonical_snapshot(model, expected_fields):
    assert set(model.model_fields.keys()) == expected_fields


def test_oss_submission_request_rejects_legacy_authenticated_fields():
    """D19 contract: OssSubmissionRequest must reject installation_id and consent_state."""
    base = {
        "envelope_contract_version": SUPPORTED_CONTRACT_VERSION,
        "envelope": {
            "source_system": "oss",
            "source_session_id": "sess-1",
            "schema_version": SUPPORTED_CONTRACT_VERSION,
            "payload": {"foo": "bar"},
            "payload_size_bytes": 13,
            "redaction_manifest": {
                "manifest_version": REDACTION_MANIFEST_VERSION,
                "redaction_applied": True,
                "redacted_fields": ["prompts", "responses", "user_identifiers"],
            },
        },
    }
    OssSubmissionRequest.model_validate(base)  # baseline must accept

    with pytest.raises(ValidationError):
        OssSubmissionRequest.model_validate({**base, "installation_id": "should-not-be-here"})

    with pytest.raises(ValidationError):
        OssSubmissionRequest.model_validate({
            **base,
            "consent_state": {
                "consent_version": SUPPORTED_CONTRACT_VERSION,
                "consent_granted": True,
                "captured_at": "2026-05-16T00:00:00+00:00",
            },
        })


def test_envelope_workflow_reference_defaults_to_constant_when_omitted():
    """phase3g.v1 envelope tightens workflow_reference to required-with-default 'default'."""
    envelope = SubmissionEnvelope.model_validate(
        {
            "source_system": "oss",
            "source_session_id": "sess-1",
            "schema_version": SUPPORTED_CONTRACT_VERSION,
            "payload": {"foo": "bar"},
            "payload_size_bytes": 13,
            "redaction_manifest": {
                "manifest_version": REDACTION_MANIFEST_VERSION,
                "redaction_applied": True,
                "redacted_fields": ["prompts", "responses", "user_identifiers"],
            },
        }
    )
    assert envelope.workflow_reference == DEFAULT_WORKFLOW_REFERENCE


def test_envelope_accepts_new_optional_provenance_fields():
    """agent_id / model_name / model_version are optional on the envelope."""
    envelope = SubmissionEnvelope.model_validate(
        {
            "source_system": "oss",
            "source_session_id": "sess-1",
            "schema_version": SUPPORTED_CONTRACT_VERSION,
            "payload": {"foo": "bar"},
            "payload_size_bytes": 13,
            "redaction_manifest": {
                "manifest_version": REDACTION_MANIFEST_VERSION,
                "redaction_applied": True,
                "redacted_fields": ["prompts", "responses", "user_identifiers"],
            },
            "agent_id": "agent-42",
            "model_name": "claude-opus-4-7",
            "model_version": "2026-05",
        }
    )
    assert envelope.agent_id == "agent-42"
    assert envelope.model_name == "claude-opus-4-7"
    assert envelope.model_version == "2026-05"


def test_envelope_rejects_unknown_sibling_field_alongside_new_optional_fields():
    """extra='forbid' must still reject unknown fields after the phase3g.v1 widening."""
    base = {
        "source_system": "oss",
        "source_session_id": "sess-1",
        "schema_version": SUPPORTED_CONTRACT_VERSION,
        "payload": {"foo": "bar"},
        "payload_size_bytes": 13,
        "redaction_manifest": {
            "manifest_version": REDACTION_MANIFEST_VERSION,
            "redaction_applied": True,
            "redacted_fields": ["prompts", "responses", "user_identifiers"],
        },
    }
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate({**base, "rogue_sibling": "x"})


def test_contract_rejects_extra_fields():
    base_manifest = {
        "manifest_version": REDACTION_MANIFEST_VERSION,
        "redaction_applied": True,
        "redacted_fields": ["prompts", "responses", "user_identifiers"],
    }
    base_consent = {
        "consent_version": SUPPORTED_CONTRACT_VERSION,
        "consent_granted": True,
        "captured_at": datetime.now(UTC).isoformat(),
    }
    base_envelope = {
        "source_system": "oss",
        "source_session_id": "sess-1",
        "schema_version": SUPPORTED_CONTRACT_VERSION,
        "payload": {"foo": "bar"},
        "payload_size_bytes": 13,
        "redaction_manifest": base_manifest,
    }
    base_request = {
        "installation_id": "oss-fallback-installation",
        "envelope_contract_version": SUPPORTED_CONTRACT_VERSION,
        "consent_state": base_consent,
        "envelope": base_envelope,
    }

    with pytest.raises(ValidationError):
        RedactionManifest.model_validate({**base_manifest, "rogue": "x"})
    with pytest.raises(ValidationError):
        ConsentState.model_validate({**base_consent, "rogue": "x"})
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate({**base_envelope, "rogue": "x"})
    with pytest.raises(ValidationError):
        IntakeSubmissionRequest.model_validate({**base_request, "rogue": "x"})


def test_redaction_manifest_requires_non_empty_redacted_fields():
    with pytest.raises(ValidationError):
        RedactionManifest.model_validate(
            {
                "manifest_version": REDACTION_MANIFEST_VERSION,
                "redaction_applied": True,
                "redacted_fields": [],
            }
        )


def test_payload_size_bytes_bounds_match_canonical():
    base = {
        "source_system": "oss",
        "source_session_id": "sess-1",
        "schema_version": SUPPORTED_CONTRACT_VERSION,
        "payload": {"foo": "bar"},
        "redaction_manifest": {
            "manifest_version": REDACTION_MANIFEST_VERSION,
            "redaction_applied": True,
            "redacted_fields": ["prompts", "responses", "user_identifiers"],
        },
    }
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate({**base, "payload_size_bytes": 0})
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate({**base, "payload_size_bytes": MAX_ENVELOPE_BYTES + 1})

    accepted = SubmissionEnvelope.model_validate({**base, "payload_size_bytes": 1})
    assert accepted.payload_size_bytes == 1
