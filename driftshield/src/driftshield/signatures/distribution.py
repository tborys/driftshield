from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePath
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen

from driftshield.signatures.community import CommunityPackManifest, parse_community_pack

DEFAULT_COMMUNITY_REPOSITORY = "tborys/driftshield"
DEFAULT_COMMUNITY_PACK_PATH = "driftshield/src/driftshield/signatures/packs"
DEFAULT_DISTRIBUTION_MANIFEST_NAME = "signature-pack-manifest.json"
DEFAULT_DISTRIBUTION_PACK_NAME = "signature-pack.json"


@dataclass(frozen=True, slots=True)
class PulledCommunityPack:
    source_url: str
    installed_path: Path
    manifest: CommunityPackManifest
    manifest_url: str | None = None
    used_cached_pack: bool = False


@dataclass(frozen=True, slots=True)
class DistributionManifest:
    manifest_version: str
    schema_version: str
    pack_name: str
    pack_version: str
    minimum_oss_version: str
    signature_count: int
    artifact_checksum: str
    artifact_url: str | None = None


def build_github_raw_pack_url(
    *,
    repository: str = DEFAULT_COMMUNITY_REPOSITORY,
    ref: str,
    pack_name: str,
    pack_path: str = DEFAULT_COMMUNITY_PACK_PATH,
) -> str:
    owner, repo = repository.split("/", maxsplit=1)
    encoded_ref = quote(ref, safe="")
    relative_pack_path = "/".join(part.strip("/") for part in (pack_path, f"{pack_name}.json"))
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{encoded_ref}/{relative_pack_path}"


def build_github_raw_manifest_url(
    *,
    repository: str = DEFAULT_COMMUNITY_REPOSITORY,
    ref: str,
    manifest_name: str = DEFAULT_DISTRIBUTION_MANIFEST_NAME,
    pack_path: str = DEFAULT_COMMUNITY_PACK_PATH,
) -> str:
    owner, repo = repository.split("/", maxsplit=1)
    encoded_ref = quote(ref, safe="")
    relative_manifest_path = "/".join(part.strip("/") for part in (pack_path, manifest_name))
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{encoded_ref}/{relative_manifest_path}"


def install_community_pack(
    *,
    source_url: str,
    destination: Path | None = None,
    pack_name_hint: str | None = None,
) -> PulledCommunityPack:
    try:
        payload = _download_json_payload(source_url)
    except OSError:
        return _load_cached_pack(pack_name=pack_name_hint or "", destination=destination)

    if _looks_like_distribution_manifest(payload):
        return _install_from_distribution_manifest(
            source_url=source_url,
            payload=payload,
            destination=destination,
            pack_name_hint=pack_name_hint,
        )

    manifest = parse_community_pack(payload)
    if manifest.pack_kind != "community":
        raise ValueError(
            f"unsupported pack_kind {manifest.pack_kind!r}; expected 'community' for OSS distribution"
        )

    target_path = destination or default_pack_install_path(
        pack_name=manifest.metadata.name,
        version=manifest.metadata.version,
    )
    _write_pack_payload(target_path=target_path, payload=payload)
    return PulledCommunityPack(
        source_url=source_url,
        installed_path=target_path,
        manifest=manifest,
    )


def default_pack_install_path(*, pack_name: str, version: str) -> Path:
    safe_pack_name = _require_safe_path_component(pack_name, field_name="pack_metadata.name")
    safe_version = _require_safe_path_component(version, field_name="pack_metadata.version")
    return _default_cache_root() / safe_pack_name / safe_version / f"{safe_pack_name}.json"


def default_manifest_install_path(*, pack_name: str, version: str) -> Path:
    return default_pack_install_path(pack_name=pack_name, version=version).with_name(
        DEFAULT_DISTRIBUTION_MANIFEST_NAME
    )


def describe_pack_source(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https", "file"}:
        return source_url
    return str(Path(source_url).expanduser().resolve())


def _install_from_distribution_manifest(
    *,
    source_url: str,
    payload: dict[str, object],
    destination: Path | None,
    pack_name_hint: str | None,
) -> PulledCommunityPack:
    distribution_manifest = _parse_distribution_manifest(payload)
    pack_url = _resolve_pack_url(source_url=source_url, distribution_manifest=distribution_manifest)
    try:
        pack_payload = _download_json_payload(pack_url)
    except OSError:
        return _load_cached_pack(pack_name=distribution_manifest.pack_name or pack_name_hint or "", destination=destination)

    pack_json = json.dumps(pack_payload, indent=2, sort_keys=True) + "\n"
    artifact_checksum = sha256(pack_json.encode("utf-8")).hexdigest()
    if artifact_checksum != distribution_manifest.artifact_checksum:
        raise ValueError(
            "downloaded signature pack checksum did not match the manifest artifact_checksum"
        )

    manifest = parse_community_pack(pack_payload)
    if manifest.pack_kind != "community":
        raise ValueError(
            f"unsupported pack_kind {manifest.pack_kind!r}; expected 'community' for OSS distribution"
        )
    if manifest.metadata.name != distribution_manifest.pack_name:
        raise ValueError("downloaded signature pack name did not match the manifest pack_name")
    if manifest.metadata.version != distribution_manifest.pack_version:
        raise ValueError("downloaded signature pack version did not match the manifest pack_version")
    if len(manifest.signatures) != distribution_manifest.signature_count:
        raise ValueError("downloaded signature pack signature count did not match the manifest")

    target_path = destination or default_pack_install_path(
        pack_name=manifest.metadata.name,
        version=manifest.metadata.version,
    )
    _write_pack_payload(target_path=target_path, payload=pack_payload)
    if destination is None:
        default_manifest_install_path(
            pack_name=manifest.metadata.name,
            version=manifest.metadata.version,
        ).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return PulledCommunityPack(
        source_url=pack_url,
        installed_path=target_path,
        manifest=manifest,
        manifest_url=source_url,
    )


def _download_json_payload(source_url: str) -> dict[str, object]:
    with urlopen(source_url) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("downloaded payload must be a JSON object")
    return payload


def _looks_like_distribution_manifest(payload: dict[str, object]) -> bool:
    return "manifest_version" in payload and "artifact_checksum" in payload


def _parse_distribution_manifest(payload: dict[str, object]) -> DistributionManifest:
    return DistributionManifest(
        manifest_version=_require_non_empty_string(payload.get("manifest_version"), field_name="manifest_version"),
        schema_version=_require_non_empty_string(payload.get("schema_version"), field_name="schema_version"),
        pack_name=_require_non_empty_string(payload.get("pack_name"), field_name="pack_name"),
        pack_version=_require_non_empty_string(payload.get("pack_version"), field_name="pack_version"),
        minimum_oss_version=_require_non_empty_string(
            payload.get("minimum_oss_version"), field_name="minimum_oss_version"
        ),
        signature_count=_require_non_negative_int(payload.get("signature_count"), field_name="signature_count"),
        artifact_checksum=_require_hex_checksum(payload.get("artifact_checksum")),
        artifact_url=_optional_non_empty_string(payload.get("artifact_url")),
    )


def _resolve_pack_url(*, source_url: str, distribution_manifest: DistributionManifest) -> str:
    if distribution_manifest.artifact_url is not None:
        return distribution_manifest.artifact_url
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https"}:
        return urljoin(source_url, DEFAULT_DISTRIBUTION_PACK_NAME)
    return str(Path(source_url).resolve().with_name(DEFAULT_DISTRIBUTION_PACK_NAME))


def _load_cached_pack(*, pack_name: str, destination: Path | None) -> PulledCommunityPack:
    cached_path = _find_latest_cached_pack(pack_name=pack_name)
    if cached_path is None:
        raise OSError("remote signature pack was unavailable and no cached pack was found")

    payload = json.loads(cached_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cached signature pack must be a JSON object")
    manifest = parse_community_pack(payload)
    target_path = destination or cached_path
    if destination is not None:
        _write_pack_payload(target_path=destination, payload=payload)
    return PulledCommunityPack(
        source_url=str(cached_path),
        installed_path=target_path,
        manifest=manifest,
        manifest_url=(
            str(cached_path.with_name(DEFAULT_DISTRIBUTION_MANIFEST_NAME))
            if cached_path.with_name(DEFAULT_DISTRIBUTION_MANIFEST_NAME).exists()
            else None
        ),
        used_cached_pack=True,
    )


def _find_latest_cached_pack(*, pack_name: str) -> Path | None:
    if not pack_name.strip():
        return None
    root = _default_cache_root() / _require_safe_path_component(pack_name, field_name="pack_name")
    if not root.exists():
        return None

    candidates: list[tuple[float, Path]] = []
    for version_dir in root.iterdir():
        if not version_dir.is_dir():
            continue
        candidate = version_dir / f"{root.name}.json"
        if candidate.exists():
            candidates.append((candidate.stat().st_mtime, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _write_pack_payload(*, target_path: Path, payload: dict[str, object]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_cache_root() -> Path:
    return Path.home() / ".local" / "share" / "driftshield" / "signatures"


def _require_safe_path_component(value: str, *, field_name: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field_name} is required")

    pure_path = PurePath(candidate)
    if (
        pure_path.name != candidate
        or len(pure_path.parts) != 1
        or candidate in {".", ".."}
        or candidate.startswith(("/", "\\"))
    ):
        raise ValueError(f"{field_name} must be a single safe path component")
    return candidate


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_non_empty_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional string fields must be non-empty when provided")
    return value.strip()


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_hex_checksum(value: object) -> str:
    checksum = _require_non_empty_string(value, field_name="artifact_checksum")
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.lower()):
        raise ValueError("artifact_checksum must be a 64-character hexadecimal sha256 digest")
    return checksum.lower()
