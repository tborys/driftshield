from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield.signatures import (
    CommunityPack,
    SignatureProvider,
    SignatureSeverity,
    load_builtin_community_pack,
)
from driftshield.signatures.community import load_community_pack, parse_community_pack


def test_builtin_community_pack_validates_and_projects_to_public_provider() -> None:
    manifest = load_builtin_community_pack()
    provider = CommunityPack(manifest)

    signatures = list(provider.iter_signatures())

    assert isinstance(provider, SignatureProvider)
    assert manifest.schema_version == "1.0.0"
    assert manifest.metadata.name == "community-general"
    assert manifest.pack_kind == "community"
    assert manifest.family_coverage == (
        "coverage_gap",
        "verification_failure",
        "assumption_mutation",
        "policy_divergence",
        "retrieval_omission",
        "state_conflict",
        "tool_misuse",
    )
    assert len(signatures) == 7
    assert signatures[0].signature_id == "SIG-COMM-001"
    assert signatures[1].severity == SignatureSeverity.HIGH
    assert {signature.signature_id for signature in signatures} == {
        "SIG-COMM-001",
        "SIG-COMM-002",
        "SIG-COMM-003",
        "SIG-COMM-004",
        "SIG-COMM-005",
        "SIG-COMM-006",
        "SIG-COMM-007",
    }


def test_load_community_pack_accepts_traversable_resources() -> None:
    class InlineTraversable:
        def read_text(self, encoding: str = "utf-8") -> str:
            assert encoding == "utf-8"
            return json.dumps(
                {
                    "schema_version": "1.0.0",
                    "pack_metadata": {
                        "name": "community-general",
                        "version": "1.0.0",
                        "description": "General-purpose DriftShield community signatures.",
                        "pack_kind": "community",
                        "family_coverage": ["coverage_gap"],
                    },
                    "signatures": [
                        {
                            "signature_id": "SIG-COMM-001",
                            "family_id": "coverage_gap",
                            "title": "Missing Retrieved Entities",
                            "signature_layer": {
                                "surface": "output",
                                "symptom": "missing key entities in response",
                                "suspected_root_cause": "retrieval did not return full context",
                                "pattern_hint": "coverage_gap",
                            },
                            "failure_shape": "retrieve->synthesise->respond",
                        }
                    ],
                }
            )

    manifest = load_community_pack(InlineTraversable())

    assert manifest.schema_version == "1.0.0"
    assert manifest.family_coverage == ("coverage_gap",)


def test_builtin_pack_json_looks_like_phase_2a_contract() -> None:
    pack_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "driftshield"
        / "signatures"
        / "packs"
        / "community-general.json"
    )
    payload = json.loads(pack_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0.0"
    assert payload["pack_metadata"]["pack_kind"] == "community"
    assert payload["pack_metadata"]["family_coverage"] == [
        "coverage_gap",
        "verification_failure",
        "assumption_mutation",
        "policy_divergence",
        "retrieval_omission",
        "state_conflict",
        "tool_misuse",
    ]
    assert payload["signatures"][0]["signature_layer"]["pattern_hint"] == "coverage_gap"
    first_wave_families = {"policy_divergence", "retrieval_omission", "state_conflict", "tool_misuse"}
    covered_first_wave = {
        signature["family_id"]
        for signature in payload["signatures"]
        if signature["family_id"] in first_wave_families
    }
    assert covered_first_wave == first_wave_families
    for signature in payload["signatures"]:
        assert signature["signature_layer"]["pattern_hint"] == signature["family_id"]


@pytest.mark.parametrize(
    "payload, expected_message",
    [
        (
            [],
            "manifest must be an object",
        ),
        (
            {
                "schema_version": "2.0.0",
                "pack_metadata": {
                    "name": "community-general",
                    "version": "1.0.0",
                    "description": "General-purpose DriftShield community signatures.",
                    "pack_kind": "community",
                    "family_coverage": [],
                },
                "signatures": [],
            },
            "unsupported schema_version",
        ),
        (
            {
                "schema_version": "1.0.0",
                "pack_metadata": {
                    "name": "community-general",
                    "version": "1.0.0",
                    "description": "General-purpose DriftShield community signatures.",
                    "pack_kind": "community",
                    "family_coverage": ["coverage_gap", "coverage_gap"],
                },
                "signatures": [],
            },
            "must not contain duplicates",
        ),
        (
            {
                "schema_version": "1.0.0",
                "pack_metadata": {
                    "name": "community-general",
                    "version": "1.0.0",
                    "description": "General-purpose DriftShield community signatures.",
                    "pack_kind": "community",
                    "family_coverage": [],
                },
                "signatures": [
                    {
                        "signature_id": "SIG-COMM-001",
                        "family_id": "coverage_gap",
                        "title": "Missing Retrieved Entities",
                        "signature_layer": {
                            "surface": "output",
                            "symptom": "missing key entities in response",
                            "suspected_root_cause": "retrieval did not return full context",
                            "pattern_hint": "coverage_gap",
                        },
                        "failure_shape": "retrieve->synthesise->respond",
                    }
                ],
            },
            "family_coverage is required when signatures are present",
        ),
        (
            {
                "schema_version": "1.0.0",
                "pack_metadata": {
                    "name": "community-general",
                    "version": "1.0.0",
                    "description": "General-purpose DriftShield community signatures.",
                    "pack_kind": "community",
                    "family_coverage": ["verification_failure"],
                },
                "signatures": [
                    {
                        "signature_id": "SIG-COMM-001",
                        "family_id": "coverage_gap",
                        "title": "Missing Retrieved Entities",
                        "signature_layer": {
                            "surface": "output",
                            "symptom": "missing key entities in response",
                            "suspected_root_cause": "retrieval did not return full context",
                            "pattern_hint": "coverage_gap",
                        },
                        "failure_shape": "retrieve->synthesise->respond",
                    }
                ],
            },
            "family_coverage must match the family_id values declared by signatures",
        ),
    ],
)
def test_parse_community_pack_rejects_incompatible_or_inconsistent_manifests(
    payload: dict[str, object], expected_message: str
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        parse_community_pack(payload)
