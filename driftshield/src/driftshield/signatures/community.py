from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from driftshield.signatures import (
    SignatureDefinition,
    SignaturePackMetadata,
    SignatureProvider,
    SignatureSeverity,
)

SUPPORTED_SCHEMA_MAJOR = 1


@dataclass(frozen=True, slots=True)
class CommunityPackManifest:
    """Validated Phase 2a community pack manifest."""

    schema_version: str
    metadata: SignaturePackMetadata
    family_coverage: tuple[str, ...]
    pack_kind: str
    signatures: tuple[SignatureDefinition, ...]


class CommunityPack(SignatureProvider):
    """Provider wrapper over a validated Phase 2a community pack manifest."""

    def __init__(self, manifest: CommunityPackManifest) -> None:
        self.manifest = manifest

    def describe(self) -> SignaturePackMetadata:
        return self.manifest.metadata

    def iter_signatures(self) -> Iterable[SignatureDefinition]:
        return iter(self.manifest.signatures)


def load_builtin_community_pack() -> CommunityPackManifest:
    """Load the bundled community pack manifest shipped with the OSS package."""

    package_file = (
        resources.files("driftshield.signatures") / "packs" / "community-general.json"
    )
    return load_community_pack(package_file)


def load_community_pack(path: str | Path) -> CommunityPackManifest:
    """Load and validate a Phase 2a community pack manifest from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_community_pack(payload)


def parse_community_pack(payload: Mapping[str, Any]) -> CommunityPackManifest:
    """Validate a raw Phase 2a community pack manifest and project it to the OSS seam."""

    schema_version = _require_non_empty_string(
        payload.get("schema_version"), field_name="schema_version"
    )
    _validate_schema_version(schema_version)

    metadata_payload = _require_mapping(
        payload.get("pack_metadata"), field_name="pack_metadata"
    )
    signatures_payload = _require_sequence(
        payload.get("signatures"), field_name="signatures"
    )

    metadata = SignaturePackMetadata(
        name=_require_non_empty_string(metadata_payload.get("name"), field_name="pack_metadata.name"),
        version=_require_non_empty_string(
            metadata_payload.get("version"), field_name="pack_metadata.version"
        ),
        description=_require_non_empty_string(
            metadata_payload.get("description"), field_name="pack_metadata.description"
        ),
        homepage_url=_optional_non_empty_string(metadata_payload.get("homepage_url")),
        documentation_url=_optional_non_empty_string(metadata_payload.get("documentation_url")),
    )
    pack_kind = _require_non_empty_string(
        metadata_payload.get("pack_kind"), field_name="pack_metadata.pack_kind"
    )
    family_coverage = tuple(
        _require_non_empty_string(family_id, field_name="pack_metadata.family_coverage[]")
        for family_id in _require_sequence(
            metadata_payload.get("family_coverage"), field_name="pack_metadata.family_coverage"
        )
    )

    signatures = tuple(_parse_signature(item) for item in signatures_payload)
    _validate_family_coverage(family_coverage=family_coverage, signatures=signatures)

    return CommunityPackManifest(
        schema_version=schema_version,
        metadata=metadata,
        family_coverage=family_coverage,
        pack_kind=pack_kind,
        signatures=signatures,
    )


def _parse_signature(payload: Any) -> SignatureDefinition:
    signature_payload = _require_mapping(payload, field_name="signatures[]")
    _require_non_empty_string(
        signature_payload.get("family_id"), field_name="signatures[].family_id"
    )
    _require_mapping(
        signature_payload.get("signature_layer"), field_name="signatures[].signature_layer"
    )

    return SignatureDefinition(
        signature_id=_require_non_empty_string(
            signature_payload.get("signature_id"), field_name="signatures[].signature_id"
        ),
        title=_require_non_empty_string(
            signature_payload.get("title"), field_name="signatures[].title"
        ),
        summary=_derive_summary(signature_payload),
        failure_shape=_require_non_empty_string(
            signature_payload.get("failure_shape"), field_name="signatures[].failure_shape"
        ),
        severity=_parse_severity(signature_payload.get("severity")),
        lexical_markers=_parse_string_sequence(
            signature_payload.get("lexical_markers", ()), field_name="signatures[].lexical_markers"
        ),
        temporal_constraints=_parse_string_sequence(
            signature_payload.get("temporal_constraints", ()),
            field_name="signatures[].temporal_constraints",
        ),
        tags=_parse_string_sequence(signature_payload.get("tags", ()), field_name="signatures[].tags"),
    )


def _derive_summary(payload: Mapping[str, Any]) -> str:
    summary = _optional_non_empty_string(payload.get("summary"))
    if summary is not None:
        return summary

    signature_layer = _require_mapping(
        payload.get("signature_layer"), field_name="signatures[].signature_layer"
    )
    return _require_non_empty_string(
        signature_layer.get("symptom"), field_name="signatures[].signature_layer.symptom"
    )


def _validate_schema_version(schema_version: str) -> None:
    major_token = schema_version.split(".", maxsplit=1)[0]
    if not major_token.isdigit() or int(major_token) != SUPPORTED_SCHEMA_MAJOR:
        raise ValueError(
            f"unsupported schema_version {schema_version!r}; expected major version {SUPPORTED_SCHEMA_MAJOR}"
        )


def _validate_family_coverage(
    *, family_coverage: Sequence[str], signatures: Sequence[SignatureDefinition]
) -> None:
    if len(set(family_coverage)) != len(family_coverage):
        raise ValueError("pack_metadata.family_coverage must not contain duplicates")

    if not signatures and family_coverage:
        raise ValueError("pack_metadata.family_coverage must be empty when signatures is empty")

    signature_count = len(signatures)
    if signature_count and not family_coverage:
        raise ValueError("pack_metadata.family_coverage is required when signatures are present")


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_sequence(value: Any, *, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be an array")
    return value


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_non_empty_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional string fields must be non-empty when provided")
    return value.strip()


def _parse_string_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_non_empty_string(item, field_name=f"{field_name}[]")
        for item in _require_sequence(value, field_name=field_name)
    )


def _parse_severity(value: Any) -> SignatureSeverity:
    if value is None:
        return SignatureSeverity.MEDIUM
    severity = _require_non_empty_string(value, field_name="signatures[].severity")
    try:
        return SignatureSeverity(severity)
    except ValueError as exc:
        raise ValueError(f"unsupported severity {severity!r}") from exc
