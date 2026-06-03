"""Structural pin for the phase3g.v1 intake contract.

Locks the OSS-side Pydantic models against a hardcoded reference
snapshot that mirrors the server-side validator. If either side moves
without the other, the intake validator will reject submissions silently
or with a misleading error code. Update both the reference snapshot
below AND ``src/driftshield/intake_contract.py`` in lockstep, and keep
the server-side validator in sync.
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
        "signature_summary",
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


# ---------------------------------------------------------------------------
# signature_summary block (envelope-level sibling of payload)
# ---------------------------------------------------------------------------


from driftshield.intake_contract import (  # noqa: E402
    ACCEPTED_SIGNATURE_SUMMARY_VERSIONS,
    MAX_SIGNATURE_SUMMARY_ENTRIES,
    SIGNATURE_SUMMARY_VERSION,
    SignatureSummary,
    SignatureSummaryEntry,
)


_BASE_ENTRY = {
    "signature_id": "sig-abc",
    "match_status": "matched",
    "community_pack_id": "community-general",
    "community_pack_version": "1.0.0",
    "matcher_id": "phase-3g-deterministic-v1",
    "matcher_version": "phase-3g-deterministic-rules-v1",
}


def _envelope_body(*, signature_summary: dict | None = None) -> dict:
    body = {
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
    if signature_summary is not None:
        body["signature_summary"] = signature_summary
    return body


def test_signature_summary_constants_match_canonical_snapshot():
    assert SIGNATURE_SUMMARY_VERSION == "signature-summary.v1"
    assert ACCEPTED_SIGNATURE_SUMMARY_VERSIONS == frozenset({SIGNATURE_SUMMARY_VERSION})
    assert MAX_SIGNATURE_SUMMARY_ENTRIES == 50


def test_envelope_signature_summary_optional():
    envelope = SubmissionEnvelope.model_validate(_envelope_body())
    assert envelope.signature_summary is None


def test_envelope_accepts_signature_summary():
    summary = {
        "schema_version": SIGNATURE_SUMMARY_VERSION,
        "matches": [
            {**_BASE_ENTRY, "confidence": 0.85, "confidence_band": "high"},
        ],
    }
    envelope = SubmissionEnvelope.model_validate(
        _envelope_body(signature_summary=summary)
    )
    assert envelope.signature_summary is not None
    assert envelope.signature_summary.schema_version == SIGNATURE_SUMMARY_VERSION
    assert len(envelope.signature_summary.matches) == 1
    entry = envelope.signature_summary.matches[0]
    assert entry.signature_id == "sig-abc"
    assert entry.confidence == 0.85
    assert entry.confidence_band == "high"

    # OssSubmissionRequest carries the block through to the request body.
    request = OssSubmissionRequest.model_validate(
        {
            "envelope_contract_version": SUPPORTED_CONTRACT_VERSION,
            "envelope": _envelope_body(signature_summary=summary),
        }
    )
    assert request.envelope.signature_summary is not None
    assert request.envelope.signature_summary.matches[0].signature_id == "sig-abc"


def test_envelope_rejects_unknown_signature_summary_fields():
    summary = {
        "schema_version": SIGNATURE_SUMMARY_VERSION,
        "matches": [{**_BASE_ENTRY, "rogue": "value"}],
    }
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate(_envelope_body(signature_summary=summary))

    summary_with_extra_top = {
        "schema_version": SIGNATURE_SUMMARY_VERSION,
        "matches": [],
        "rogue_top": "x",
    }
    with pytest.raises(ValidationError):
        SubmissionEnvelope.model_validate(
            _envelope_body(signature_summary=summary_with_extra_top)
        )


@pytest.mark.parametrize(
    "field_name, max_length",
    [
        ("signature_id", 64),
        ("community_pack_version", 32),
        ("matcher_version", 40),
    ],
)
def test_signature_summary_per_field_caps_enforced(field_name, max_length):
    at_cap = {**_BASE_ENTRY, field_name: "a" * max_length}
    accepted = SignatureSummaryEntry.model_validate(at_cap)
    assert getattr(accepted, field_name) == "a" * max_length

    over_cap = {**_BASE_ENTRY, field_name: "a" * (max_length + 1)}
    with pytest.raises(ValidationError):
        SignatureSummaryEntry.model_validate(over_cap)


def test_signature_summary_50_entry_cap():
    base_matches = [dict(_BASE_ENTRY) for _ in range(MAX_SIGNATURE_SUMMARY_ENTRIES)]
    accepted = SignatureSummary.model_validate(
        {
            "schema_version": SIGNATURE_SUMMARY_VERSION,
            "matches": base_matches,
        }
    )
    assert len(accepted.matches) == MAX_SIGNATURE_SUMMARY_ENTRIES

    over_cap_matches = [dict(_BASE_ENTRY) for _ in range(MAX_SIGNATURE_SUMMARY_ENTRIES + 1)]
    with pytest.raises(ValidationError):
        SignatureSummary.model_validate(
            {
                "schema_version": SIGNATURE_SUMMARY_VERSION,
                "matches": over_cap_matches,
            }
        )


def test_signature_summary_confidence_bounds():
    with pytest.raises(ValidationError):
        SignatureSummaryEntry.model_validate({**_BASE_ENTRY, "confidence": 1.5})
    with pytest.raises(ValidationError):
        SignatureSummaryEntry.model_validate({**_BASE_ENTRY, "confidence": -0.1})

    accepted = SignatureSummaryEntry.model_validate({**_BASE_ENTRY, "confidence": 0.0})
    assert accepted.confidence == 0.0
