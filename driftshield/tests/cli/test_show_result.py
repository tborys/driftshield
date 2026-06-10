"""Tests for the `driftshield show-result` command."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib import error

from typer.testing import CliRunner

from driftshield.cli.commands.show_result import _derive_submission_url
from driftshield.cli.main import app


runner = CliRunner()


_OSS_TEST_INTAKE_URL = "https://example.test/v1/oss/submissions"


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _seed_remote_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(
        app,
        ["telemetry", "remote-enable", "--intake-url", _OSS_TEST_INTAKE_URL],
    )


def test_derive_submission_url_strips_v1_intake_suffix():
    assert (
        _derive_submission_url("https://example.test/v1/intake", "sub_abc")
        == "https://example.test/v1/oss/submissions/sub_abc"
    )


def test_derive_submission_url_strips_v1_oss_submissions_suffix():
    assert (
        _derive_submission_url("https://example.test/v1/oss/submissions", "sub_abc")
        == "https://example.test/v1/oss/submissions/sub_abc"
    )


def test_derive_submission_url_appends_when_no_known_suffix():
    assert (
        _derive_submission_url("https://example.test", "sub_abc")
        == "https://example.test/v1/oss/submissions/sub_abc"
    )


def test_derive_submission_url_strips_trailing_slash():
    assert (
        _derive_submission_url("https://example.test/", "sub_abc")
        == "https://example.test/v1/oss/submissions/sub_abc"
    )


def test_show_result_happy_path(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.headers)
        return _FakeHttpResponse(
            json.dumps({
                "submission_id": "sub_abc",
                "processing_status": "processed",
                "signature_label": "drift_signature_v1",
                "signature_family": "tool_misuse",
                "confidence_band": "high",
            }).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_abc"])

    assert result.exit_code == 0
    assert "sub_abc" in result.stdout
    assert "processed" in result.stdout
    assert "drift_signature_v1" in result.stdout
    assert "tool_misuse" in result.stdout
    assert "high" in result.stdout

    assert captured["url"] == "https://example.test/v1/oss/submissions/sub_abc"
    assert captured["method"] == "GET"
    # urllib stores X-API-Key under "X-api-key" — assert it's NOT present (Option A: no auth header).
    assert "X-api-key" not in captured["headers"]
    assert "Authorization" not in captured["headers"]


def test_show_result_renders_nulls_gracefully(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(
            json.dumps({
                "submission_id": "sub_pending",
                "processing_status": "processing",
                "signature_label": None,
                "signature_family": None,
                "confidence_band": None,
            }).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_pending"])

    assert result.exit_code == 0
    assert "sub_pending" in result.stdout
    assert "processing" in result.stdout
    assert "not yet matched" in result.stdout
    assert "not yet evaluated" in result.stdout


def test_show_result_json_output(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    body = {
        "submission_id": "sub_abc",
        "processing_status": "processed",
        "signature_label": "drift_signature_v1",
        "signature_family": "tool_misuse",
        "confidence_band": "high",
    }

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_abc", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout.strip())
    assert parsed == body


def test_show_result_overrides_intake_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    # No remote-enable; passing --intake-url instead.

    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        return _FakeHttpResponse(
            json.dumps({
                "submission_id": "sub_abc",
                "processing_status": "processed",
                "signature_label": "drift_signature_v1",
                "signature_family": "tool_misuse",
                "confidence_band": "high",
            }).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["show-result", "sub_abc", "--intake-url", "https://override.example.test/v1/intake"],
    )

    assert result.exit_code == 0
    assert captured["url"] == "https://override.example.test/v1/oss/submissions/sub_abc"


def test_show_result_zero_config_uses_community_default(tmp_path, monkeypatch):
    """With nothing configured, show-result derives from the baked community URL."""
    from driftshield.telemetry import DEFAULT_COMMUNITY_INTAKE_URL

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        return _FakeHttpResponse(
            json.dumps({
                "submission_id": "sub_abc",
                "processing_status": "processed",
                "signature_label": None,
                "signature_family": None,
                "confidence_band": None,
            }).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_abc"])

    assert result.exit_code == 0
    expected_base = DEFAULT_COMMUNITY_INTAKE_URL.removesuffix("/v1/intake")
    assert captured["url"] == f"{expected_base}/v1/oss/submissions/sub_abc"


def test_show_result_fails_after_remote_disable(tmp_path, monkeypatch):
    """remote-disable opts out of the baked default; show-result has no target."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "remote-disable"])

    result = runner.invoke(app, ["show-result", "sub_abc"])

    assert result.exit_code == 1
    assert "disabled" in result.stdout.lower()


def test_show_result_intake_url_flag_works_after_remote_disable(tmp_path, monkeypatch):
    """An explicit --intake-url is per-invocation intent and wins over the opt-out."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "remote-disable"])

    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        return _FakeHttpResponse(
            json.dumps({"submission_id": "sub_abc", "processing_status": "processed"}).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["show-result", "sub_abc", "--intake-url", "https://override.example.test/v1/intake"],
    )

    assert result.exit_code == 0
    assert captured["url"] == "https://override.example.test/v1/oss/submissions/sub_abc"


def test_show_result_404_renders_not_found(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        raise error.HTTPError(
            url="https://example.test/v1/oss/submissions/sub_missing",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"detail":"submission_not_found"}'),
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_missing"])

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_show_result_url_error(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        raise error.URLError("name resolution failed")

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_abc"])

    assert result.exit_code == 1
    assert "unreachable" in result.stdout.lower()


def test_show_result_non_json_response(tmp_path, monkeypatch):
    _seed_remote_config(tmp_path, monkeypatch)

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(b"<html>oops</html>")

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    result = runner.invoke(app, ["show-result", "sub_abc"])

    assert result.exit_code == 1
    assert "non-json" in result.stdout.lower()


def test_zero_config_submit_then_show_result_roundtrip(tmp_path, monkeypatch):
    """The full community happy path needs no remote-enable: submit-session
    resolves to the baked default and show-result fetches from the same base."""
    from driftshield.intake_contract import IntakeSubmissionResponse
    from driftshield.remote_submission import OssSubmissionResult
    from driftshield.telemetry import DEFAULT_COMMUNITY_INTAKE_URL

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps({"session_id": "sess-1"}), encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["submit_url"] = config.intake_url
        return OssSubmissionResult(
            response=IntakeSubmissionResponse(
                submission_id="sub_rt1", processing_status="received"
            ),
            server_contract_version="phase3g.v1",
        )

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )

    submit = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )
    assert submit.exit_code == 0
    assert "sub_rt1" in submit.stdout
    assert captured["submit_url"] == DEFAULT_COMMUNITY_INTAKE_URL

    def fake_urlopen(req: Any) -> _FakeHttpResponse:
        captured["result_url"] = req.full_url
        return _FakeHttpResponse(
            json.dumps({
                "submission_id": "sub_rt1",
                "processing_status": "processed",
                "signature_label": "drift_signature_v1",
                "signature_family": "tool_misuse",
                "confidence_band": "high",
            }).encode("utf-8")
        )

    monkeypatch.setattr("driftshield.cli.commands.show_result.request.urlopen", fake_urlopen)

    shown = runner.invoke(app, ["show-result", "sub_rt1"])
    assert shown.exit_code == 0
    assert "sub_rt1" in shown.stdout
    expected_base = DEFAULT_COMMUNITY_INTAKE_URL.removesuffix("/v1/intake")
    assert captured["result_url"] == f"{expected_base}/v1/oss/submissions/sub_rt1"
