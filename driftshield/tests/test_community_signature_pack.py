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
    )
    assert len(signatures) == 3
    assert signatures[0].signature_id == "SIG-COMM-001"
    assert signatures[1].severity == SignatureSeverity.HIGH


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
    ]
    assert payload["signatures"][0]["signature_layer"]["pattern_hint"] == "coverage_gap"


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
