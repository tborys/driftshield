from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import urlopen

from driftshield.signatures.community import CommunityPackManifest, parse_community_pack

DEFAULT_COMMUNITY_REPOSITORY = "tborys/driftshield"
DEFAULT_COMMUNITY_PACK_PATH = "driftshield/src/driftshield/signatures/packs"


@dataclass(frozen=True, slots=True)
class PulledCommunityPack:
    source_url: str
    installed_path: Path
    manifest: CommunityPackManifest


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


def install_community_pack(
    *,
    source_url: str,
    destination: Path | None = None,
) -> PulledCommunityPack:
    payload = _download_manifest_payload(source_url)
    manifest = parse_community_pack(payload)
    if manifest.pack_kind != "community":
        raise ValueError(
            f"unsupported pack_kind {manifest.pack_kind!r}; expected 'community' for OSS distribution"
        )

    target_path = destination or default_pack_install_path(
        pack_name=manifest.metadata.name,
        version=manifest.metadata.version,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return PulledCommunityPack(
        source_url=source_url,
        installed_path=target_path,
        manifest=manifest,
    )


def default_pack_install_path(*, pack_name: str, version: str) -> Path:
    return (
        Path.home()
        / ".local"
        / "share"
        / "driftshield"
        / "signatures"
        / pack_name
        / version
        / f"{pack_name}.json"
    )


def _download_manifest_payload(source_url: str) -> dict[str, object]:
    with urlopen(source_url) as response:
        return json.loads(response.read().decode("utf-8"))


def describe_pack_source(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https", "file"}:
        return source_url
    return str(Path(source_url).expanduser().resolve())
