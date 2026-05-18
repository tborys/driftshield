from __future__ import annotations

import json

from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.telemetry import TelemetryService


runner = CliRunner()


def test_telemetry_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["enabled"] is False
    assert payload["install_id"] is None

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 1
    assert "disabled" in heartbeat.stdout.lower()
    assert TelemetryService().read_events() == []


def test_telemetry_enable_registers_install_and_emits_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(app, ["telemetry", "enable"])
    assert enabled.exit_code == 0

    service = TelemetryService()
    config = service.load_config()
    assert config.enabled is True
    assert config.install_id is not None
    assert config.registered_at is not None

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 0

    events = service.read_events()
    assert [event["event_type"] for event in events] == ["registration", "heartbeat"]
    assert events[0]["payload"]["consent_state"] == "opted_in"
    assert events[1]["payload"]["status"] == "alive"


def test_emit_analysis_uses_phase_2a_metric_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    emitted = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            "matched",
            "--match-count",
            "2",
            "--primary-mechanism-id",
            "verification_failure",
        ],
    )
    assert emitted.exit_code == 0

    events = TelemetryService().read_events()
    analysis_event = events[-1]
    assert analysis_event["event_type"] == "analysis_result"
    assert analysis_event["payload"] == {
        "classifiable": True,
        "event_inventory_version": "phase-2a-v1",
        "match_count": 2,
        "mixed_mechanism": False,
        "not_classifiable_reason": None,
        "outcome_status": "matched",
        "primary_mechanism_id": "verification_failure",
    }


def test_disable_stops_further_emission(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, ["telemetry", "disable"])

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 1

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration"]


def test_emit_analysis_rejects_invalid_outcome_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    invalid = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            "matchd",
        ],
    )

    assert invalid.exit_code == 1
    assert "outcome_status must be one of" in invalid.stdout

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration"]


def test_emit_analysis_normalizes_outcome_status_before_classifiable_check(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    emitted = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            " matched ",
            "--match-count",
            "1",
        ],
    )

    assert emitted.exit_code == 0
    analysis_event = TelemetryService().read_events()[-1]
    assert analysis_event["payload"]["outcome_status"] == "matched"
    assert analysis_event["payload"]["classifiable"] is True


_OSS_TEST_INTAKE_URL = "https://snidz3uiv5.execute-api.eu-west-2.amazonaws.com/v1/oss/submissions"


def _remote_enable_argv(*, intake_url: str = _OSS_TEST_INTAKE_URL) -> list[str]:
    return ["telemetry", "remote-enable", "--intake-url", intake_url]


def test_status_default_shows_remote_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is False
    assert payload["remote_intake_url"] is None


def test_remote_enable_persists_intake_url_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(app, _remote_enable_argv())
    assert enabled.exit_code == 0
    assert _OSS_TEST_INTAKE_URL in enabled.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    # D19 contract: no legacy auth fields persisted.
    assert config.remote_api_key is None
    assert config.remote_installation_id is None

    status = runner.invoke(app, ["telemetry", "status", "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is True
    assert payload["remote_intake_url"] == _OSS_TEST_INTAKE_URL
    # D19 status surface dropped the legacy fields.
    assert "remote_installation_id" not in payload
    assert "remote_api_key_configured" not in payload
    assert "remote_api_key" not in payload


def test_remote_enable_rejects_only_unknown_flags(tmp_path, monkeypatch):
    """D19 contract: --api-key and --installation-id are no longer accepted as flags."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    result = runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            "should-be-rejected",
        ],
    )
    assert result.exit_code != 0


def test_remote_enable_migrates_away_from_d7_d8_legacy_fields(tmp_path, monkeypatch):
    """A config file from a prior D7/D8 install has remote_api_key + remote_installation_id.
    First D19 remote-enable run must clear them.
    """
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    home = tmp_path / "telemetry"
    home.mkdir(parents=True)
    (home / "config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "install_id": "uuid-old",
                "remote_intake_url": "https://example.test/v1/intake",
                "remote_api_key": "legacy-key",
                "remote_installation_id": "oss-fallback-installation",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, _remote_enable_argv())
    assert result.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.remote_api_key is None
    assert config.remote_installation_id is None
    # Local state preserved.
    assert config.enabled is True
    assert config.install_id == "uuid-old"


def test_remote_disable_clears_remote_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())

    disabled = runner.invoke(app, ["telemetry", "remote-disable"])
    assert disabled.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None
    assert config.remote_installation_id is None


def test_remote_enable_rejects_empty_intake_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    blank_url = runner.invoke(app, _remote_enable_argv(intake_url="   "))
    assert blank_url.exit_code == 1
    assert "intake_url" in blank_url.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None


def test_local_capture_unchanged_when_remote_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, _remote_enable_argv())
    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 0

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration", "heartbeat"]

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL


def test_remote_enable_does_not_toggle_local_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, _remote_enable_argv())
    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.enabled is False
    assert config.install_id is None


def test_remote_disable_does_not_clear_local_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, _remote_enable_argv())

    install_id_before = TelemetryService().load_config().install_id
    runner.invoke(app, ["telemetry", "remote-disable"])

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.install_id == install_id_before
    assert config.remote_intake_url is None


def _write_session(tmp_path, contents):
    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps(contents), encoding="utf-8")
    return session_path


def test_submit_session_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {
            "session_id": "sess-1",
            "prompts": ["secret"],
            "responses": ["also secret"],
            "user_identifiers": ["alice@example.test"],
            "metadata": {"foo": "bar"},
        },
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        captured["payload_keys"] = sorted(submission.envelope.payload.keys())
        captured["request_keys"] = set(json.loads(submission.model_dump_json()).keys())
        from driftshield.intake_contract import IntakeSubmissionResponse

        return IntakeSubmissionResponse(submission_id="sub_xyz", processing_status="received")

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "sub_xyz" in result.stdout
    assert "received" in result.stdout
    assert captured["intake_url"] == _OSS_TEST_INTAKE_URL
    assert "prompts" not in captured["payload_keys"]
    assert "responses" not in captured["payload_keys"]
    assert "user_identifiers" not in captured["payload_keys"]
    assert "metadata" in captured["payload_keys"]
    # D19 contract: request body has no installation_id, no consent_state.
    assert captured["request_keys"] == {"envelope_contract_version", "envelope"}


def test_submit_session_fails_when_remote_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "not configured" in result.stdout.lower()


def test_submit_session_fails_on_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    bad_path = tmp_path / "session.json"
    bad_path.write_text("not json at all", encoding="utf-8")

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(bad_path)]
    )

    assert result.exit_code == 1
    assert "not valid json" in result.stdout.lower()


def test_submit_session_fails_on_non_object_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    array_path = tmp_path / "session.json"
    array_path.write_text(json.dumps([{"session_id": "sess-1"}]), encoding="utf-8")

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(array_path)]
    )

    assert result.exit_code == 1
    assert "json object" in result.stdout.lower()


def test_submit_session_dry_run_redaction_prints_entries_and_does_not_submit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {
            "session_id": "sess-1",
            "events": [{"type": "user", "note": "ssn 123-45-6789"}],
        },
    )
    called = {"posted": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        called["posted"] = True

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--dry-run-redaction"],
    )

    assert result.exit_code == 0
    assert called["posted"] is False
    body = json.loads(result.stdout)
    assert body["detected_shape"] == "claude_code"
    assert any(entry["category"] == "ssn" for entry in body["entries"])


def test_submit_session_show_manifest_prints_manifest_and_does_not_submit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {"session_id": "sess-1", "events": []},
    )
    called = {"posted": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        called["posted"] = True

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--show-manifest"],
    )

    assert result.exit_code == 0
    assert called["posted"] is False
    manifest = json.loads(result.stdout)
    assert manifest["manifest_version"] == "redaction-manifest.v1"
    assert manifest["redaction_applied"] is True
    assert sorted(manifest["redacted_fields"]) == sorted(
        ["prompts", "responses", "user_identifiers"]
    )


def test_submit_session_refuses_unknown_shape_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"unrelated_top_key": True})

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "shape" in result.stdout.lower()


def test_submit_session_accepts_unknown_shape_when_forced(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"unrelated_top_key": True})

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        from driftshield.intake_contract import IntakeSubmissionResponse

        return IntakeSubmissionResponse(submission_id="sub_forced", processing_status="received")

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--force-unknown-shape",
        ],
    )

    assert result.exit_code == 0
    assert "sub_forced" in result.stdout


def test_submit_session_surfaces_remote_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    from driftshield.remote_submission import RemoteSubmissionError

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        raise RemoteSubmissionError("intake HTTP 422: invalid_redaction_manifest")

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_oss_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "422" in result.stdout
    assert "invalid_redaction_manifest" in result.stdout
