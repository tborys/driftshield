from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.signatures.distribution import (
    DEFAULT_DISTRIBUTION_MANIFEST_NAME,
    build_github_raw_pack_url,
    default_pack_install_path,
    default_manifest_install_path,
)


runner = CliRunner()


class DummyResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _community_pack_payload(*, version: str = "1.2.3", pack_kind: str = "community") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "pack_metadata": {
            "name": "community-general",
            "version": version,
            "description": "General-purpose DriftShield community signatures.",
            "pack_kind": pack_kind,
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


def _distribution_manifest_payload(*, pack_payload: dict[str, object]) -> dict[str, object]:
    encoded_pack = json.dumps(pack_payload, indent=2, sort_keys=True) + "\n"
    return {
        "manifest_version": "phase-3f.signature-pack-manifest.v1",
        "schema_version": "1.0.0",
        "pack_name": str(pack_payload["pack_metadata"]["name"]),
        "pack_version": str(pack_payload["pack_metadata"]["version"]),
        "minimum_oss_version": "0.1.0",
        "signature_count": len(pack_payload["signatures"]),
        "artifact_checksum": __import__("hashlib").sha256(encoded_pack.encode("utf-8")).hexdigest(),
    }


def test_build_github_raw_pack_url_uses_repository_ref_and_pack_name() -> None:
    assert build_github_raw_pack_url(
        repository="tborys/driftshield",
        ref="v1.2.3",
        pack_name="community-general",
    ) == (
        "https://raw.githubusercontent.com/tborys/driftshield/"
        "v1.2.3/driftshield/src/driftshield/signatures/packs/community-general.json"
    )


def test_pull_signature_pack_writes_versioned_manifest(monkeypatch, tmp_path: Path) -> None:
    payload = _community_pack_payload(version="1.2.3")
    manifest_payload = _distribution_manifest_payload(pack_payload=payload)

    def fake_urlopen(source_url: str) -> DummyResponse:
        if source_url == f"https://example.test/{DEFAULT_DISTRIBUTION_MANIFEST_NAME}":
            return DummyResponse(manifest_payload)
        assert source_url == "https://example.test/signature-pack.json"
        return DummyResponse(payload)

    monkeypatch.setattr("driftshield.signatures.distribution.urlopen", fake_urlopen)
    monkeypatch.setattr("driftshield.signatures.distribution.Path.home", lambda: tmp_path)

    result = runner.invoke(
        app,
        [
            "signatures",
            "pull",
            "community-general",
            "--url",
            f"https://example.test/{DEFAULT_DISTRIBUTION_MANIFEST_NAME}",
        ],
    )

    output = default_pack_install_path(pack_name="community-general", version="1.2.3")
    cached_manifest = default_manifest_install_path(pack_name="community-general", version="1.2.3")
    assert result.exit_code == 0
    assert output.exists()
    assert cached_manifest.exists()
    installed_payload = json.loads(output.read_text(encoding="utf-8"))
    assert installed_payload["pack_metadata"]["version"] == "1.2.3"
    assert "community-general@" in result.output
    assert "schema" in result.output
    assert "signature-pack-manifest.json" in result.output


def test_pull_signature_pack_allows_url_without_ref(monkeypatch, tmp_path: Path) -> None:
    payload = _community_pack_payload(version="1.2.3")

    def fake_urlopen(source_url: str) -> DummyResponse:
        assert source_url == "https://example.test/community-general.json"
        return DummyResponse(payload)

    monkeypatch.setattr("driftshield.signatures.distribution.urlopen", fake_urlopen)

    output = tmp_path / "packs" / "community-general.json"
    result = runner.invoke(
        app,
        [
            "signatures",
            "pull",
            "community-general",
            "--url",
            "https://example.test/community-general.json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()


def test_default_pack_install_path_rejects_unsafe_manifest_path_components() -> None:
    for unsafe_value in ("../escape", "nested/path", "..", "/absolute"):
        try:
            default_pack_install_path(pack_name=unsafe_value, version="1.2.3")
        except ValueError as exc:
            assert "single safe path component" in str(exc)
        else:
            raise AssertionError("unsafe pack_name should be rejected")

    try:
        default_pack_install_path(pack_name="community-general", version="../1.2.3")
    except ValueError as exc:
        assert "single safe path component" in str(exc)
    else:
        raise AssertionError("unsafe version should be rejected")


def test_pull_signature_pack_rejects_invalid_repository_value() -> None:
    for invalid_repository in ("tborys", "owner/repo/extra"):
        result = runner.invoke(
            app,
            [
                "signatures",
                "pull",
                "community-general",
                "--ref",
                "v1.2.3",
                "--repository",
                invalid_repository,
            ],
        )

        assert result.exit_code == 1
        assert "Could not pull pack" in result.output
        assert "owner/repo" in result.output


def test_pull_signature_pack_rejects_non_community_pack(monkeypatch) -> None:
    def fake_urlopen(source_url: str) -> DummyResponse:
        return DummyResponse(_community_pack_payload(pack_kind="private"))

    monkeypatch.setattr("driftshield.signatures.distribution.urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        [
            "signatures",
            "pull",
            "community-general",
            "--ref",
            "v1.2.3",
            "--url",
            "https://example.test/private-pack.json",
        ],
    )

    assert result.exit_code == 1
    assert "unsupported pack_kind" in result.output
    assert "community" in result.output


def test_pull_signature_pack_uses_cached_pack_when_remote_manifest_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    payload = _community_pack_payload(version="1.2.2")
    monkeypatch.setattr("driftshield.signatures.distribution.Path.home", lambda: tmp_path)

    cached_pack_path = default_pack_install_path(pack_name="community-general", version="1.2.2")
    cached_pack_path.parent.mkdir(parents=True, exist_ok=True)
    cached_pack_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def failing_urlopen(source_url: str) -> DummyResponse:
        raise OSError("network unavailable")

    monkeypatch.setattr("driftshield.signatures.distribution.urlopen", failing_urlopen)

    result = runner.invoke(
        app,
        [
            "signatures",
            "pull",
            "community-general",
            "--url",
            f"https://example.test/{DEFAULT_DISTRIBUTION_MANIFEST_NAME}",
        ],
    )

    assert result.exit_code == 0
    assert "Using cached community pack" in result.output


def test_pull_signature_pack_rejects_checksum_mismatch(monkeypatch, tmp_path: Path) -> None:
    payload = _community_pack_payload(version="1.2.3")
    manifest_payload = _distribution_manifest_payload(pack_payload=payload) | {
        "artifact_checksum": "0" * 64,
    }

    def fake_urlopen(source_url: str) -> DummyResponse:
        if source_url == f"https://example.test/{DEFAULT_DISTRIBUTION_MANIFEST_NAME}":
            return DummyResponse(manifest_payload)
        return DummyResponse(payload)

    monkeypatch.setattr("driftshield.signatures.distribution.urlopen", fake_urlopen)
    monkeypatch.setattr("driftshield.signatures.distribution.Path.home", lambda: tmp_path)

    result = runner.invoke(
        app,
        [
            "signatures",
            "pull",
            "community-general",
            "--url",
            f"https://example.test/{DEFAULT_DISTRIBUTION_MANIFEST_NAME}",
        ],
    )

    assert result.exit_code == 1
    assert "checksum" in result.output.lower()
