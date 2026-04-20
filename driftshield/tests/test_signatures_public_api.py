from __future__ import annotations

from collections.abc import Iterable
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from driftshield.signatures import (
    SignatureDefinition,
    SignaturePackMetadata,
    SignatureProvider,
    SignatureSeverity,
)


def test_signature_provider_protocol_accepts_external_pack() -> None:
    class ExampleProvider:
        def describe(self) -> SignaturePackMetadata:
            return SignaturePackMetadata(
                name="community-general",
                version="1.0.0",
                description="General-purpose public signatures.",
            )

        def iter_signatures(self) -> Iterable[SignatureDefinition]:
            yield SignatureDefinition(
                signature_id="SIG-COMM-001",
                title="Coverage Gap",
                summary="Task branch exits before all required evidence is checked.",
                failure_shape="collect->branch->skip->complete",
                severity=SignatureSeverity.MEDIUM,
                lexical_markers=("skip", "done", "already covered"),
                temporal_constraints=("verify all required evidence before completion",),
                tags=("coverage", "community"),
            )

    provider = ExampleProvider()
    signatures = list(provider.iter_signatures())

    assert isinstance(provider, SignatureProvider)
    assert provider.describe().name == "community-general"
    assert signatures[0].signature_id == "SIG-COMM-001"


def test_signature_definition_normalizes_optional_sequences() -> None:
    definition = SignatureDefinition(
        signature_id="SIG-PRIVATE-001",
        title="Private Signature Example",
        summary="A private pack can provide metadata without any matching logic in OSS.",
        failure_shape="observe->classify",
        lexical_markers=["marker-a", "marker-b"],
        temporal_constraints=["must happen after review"],
        tags=["private", "example"],
    )

    assert isinstance(definition.lexical_markers, tuple)
    assert definition.lexical_markers == ("marker-a", "marker-b")
    assert definition.temporal_constraints == ("must happen after review",)
    assert definition.tags == ("private", "example")
    assert definition.severity == SignatureSeverity.MEDIUM


@pytest.mark.parametrize(
    ("field_name", "value", "expected_message"),
    [
        ("signature_id", "", "signature_id is required"),
        ("title", "", "title is required"),
        ("summary", "", "summary is required"),
        ("failure_shape", "", "failure_shape is required"),
    ],
)
def test_signature_definition_requires_required_fields(
    field_name: str,
    value: str,
    expected_message: str,
) -> None:
    signature_id = value if field_name == "signature_id" else "SIG-PRIVATE-001"
    title = value if field_name == "title" else "Private Signature Example"
    summary = (
        value
        if field_name == "summary"
        else "A private pack can provide metadata without any matching logic in OSS."
    )
    failure_shape = value if field_name == "failure_shape" else "observe->classify"

    with pytest.raises(ValueError, match=expected_message):
        SignatureDefinition(
            signature_id=signature_id,
            title=title,
            summary=summary,
            failure_shape=failure_shape,
        )


@pytest.mark.parametrize(
    ("field_name", "value", "expected_message"),
    [
        ("name", "", "name is required"),
        ("version", "", "version is required"),
    ],
)
def test_signature_pack_metadata_requires_required_fields(
    field_name: str,
    value: str,
    expected_message: str,
) -> None:
    name = value if field_name == "name" else "community-general"
    version = value if field_name == "version" else "1.0.0"

    with pytest.raises(ValueError, match=expected_message):
        SignaturePackMetadata(
            name=name,
            version=version,
            description="General-purpose public signatures.",
        )


def test_public_signatures_surface_imports_without_private_modules() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(backend_root / "src")}
    script = textwrap.dedent(
        """
        import json
        import sys

        import driftshield.signatures as public_signatures

        print(
            json.dumps(
                {
                    "exports": sorted(public_signatures.__all__),
                    "private_signature_module_loaded": "driftshield.core.signatures" in sys.modules,
                    "recurrence_module_loaded": "driftshield.core.analysis.recurrence" in sys.modules,
                    "graveyard_module_loaded": "driftshield.graveyard" in sys.modules,
                }
            )
        )
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout)

    assert payload["exports"] == [
        "CommunityPack",
        "CommunityPackManifest",
        "SignatureDefinition",
        "SignaturePackMetadata",
        "SignatureProvider",
        "SignatureSeverity",
        "load_builtin_community_pack",
    ]
    assert payload["private_signature_module_loaded"] is False
    assert payload["recurrence_module_loaded"] is False
    assert payload["graveyard_module_loaded"] is False
