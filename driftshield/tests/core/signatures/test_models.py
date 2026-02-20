from dataclasses import asdict

import pytest

from driftshield.core.signatures.models import (
    DetectionSignature,
    SignatureConfidence,
    SignatureInvariant,
    SignatureProvenance,
    SignatureRiskClass,
    SignatureStatus,
)


def test_detection_signature_requires_invariant_fingerprint() -> None:
    with pytest.raises(ValueError, match="invariant_fingerprint"):
        DetectionSignature(
            signature_id="SIG-VD-001",
            title="Variable Drift Propagation",
            risk_class=SignatureRiskClass.VARIABLE_DRIFT,
            status=SignatureStatus.CANDIDATE,
            invariant=SignatureInvariant(
                graph_pattern="A->B",
                temporal_constraints=["verify before write"],
                state_constraints=["variable mapping stable"],
                lexical_markers=["as above"],
                invariant_fingerprint="",
            ),
            confidence=SignatureConfidence(model_score=0.8, reviewer_score=0.9),
            provenance=[
                SignatureProvenance(
                    source_type="github_issue",
                    source_ref="https://github.com/org/repo/issues/1",
                )
            ],
        )


def test_detection_signature_to_dict_contains_expected_fields() -> None:
    sig = DetectionSignature(
        signature_id="SIG-VD-001",
        title="Variable Drift Propagation",
        risk_class=SignatureRiskClass.VARIABLE_DRIFT,
        status=SignatureStatus.CANDIDATE,
        invariant=SignatureInvariant(
            graph_pattern="retrieve->transform->write",
            temporal_constraints=["verify before write"],
            state_constraints=["input-output variable parity"],
            lexical_markers=["using previous value"],
            invariant_fingerprint="abc123",
        ),
        confidence=SignatureConfidence(model_score=0.84, reviewer_score=0.91),
        provenance=[
            SignatureProvenance(
                source_type="github_issue",
                source_ref="https://github.com/org/repo/issues/1",
            )
        ],
    )

    payload = asdict(sig)
    assert payload["signature_id"] == "SIG-VD-001"
    assert payload["risk_class"] == SignatureRiskClass.VARIABLE_DRIFT
    assert payload["invariant"]["invariant_fingerprint"] == "abc123"
    assert payload["provenance"][0]["source_type"] == "github_issue"
