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


_OSS_TEST_INTAKE_URL = "https://snidz3uiv5.execute-api.eu-west-2.amazonaws.com/v1/intake"
_OSS_TEST_API_KEY = "test-d7-api-key-not-real"
_OSS_TEST_INSTALLATION_ID = "oss-fallback-installation"


def _remote_enable_argv(
    *,
    intake_url: str = _OSS_TEST_INTAKE_URL,
    api_key: str = _OSS_TEST_API_KEY,
    installation_id: str = _OSS_TEST_INSTALLATION_ID,
) -> list[str]:
    return [
        "telemetry",
        "remote-enable",
        "--intake-url",
        intake_url,
        "--api-key",
        api_key,
        "--installation-id",
        installation_id,
    ]


def test_status_default_shows_remote_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is False
    assert payload["remote_intake_url"] is None
    assert payload["remote_installation_id"] is None
    assert payload["remote_api_key_configured"] is False


def test_remote_enable_persists_config_and_redacts_key_in_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(app, _remote_enable_argv())
    assert enabled.exit_code == 0
    assert _OSS_TEST_API_KEY not in enabled.stdout
    assert _OSS_TEST_INSTALLATION_ID in enabled.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.remote_api_key == _OSS_TEST_API_KEY
    assert config.remote_installation_id == _OSS_TEST_INSTALLATION_ID

    status = runner.invoke(app, ["telemetry", "status", "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is True
    assert payload["remote_intake_url"] == _OSS_TEST_INTAKE_URL
    assert payload["remote_installation_id"] == _OSS_TEST_INSTALLATION_ID
    assert payload["remote_api_key_configured"] is True
    assert "remote_api_key" not in payload
    assert _OSS_TEST_API_KEY not in status.stdout


def test_remote_disable_clears_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())

    disabled = runner.invoke(app, ["telemetry", "remote-disable"])
    assert disabled.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None
    assert config.remote_installation_id is None


def test_remote_enable_rejects_empty_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    blank_url = runner.invoke(app, _remote_enable_argv(intake_url="   "))
    assert blank_url.exit_code == 1
    assert "intake_url" in blank_url.stdout

    blank_key = runner.invoke(app, _remote_enable_argv(api_key="   "))
    assert blank_key.exit_code == 1
    assert "api_key" in blank_key.stdout

    blank_install = runner.invoke(app, _remote_enable_argv(installation_id="   "))
    assert blank_install.exit_code == 1
    assert "installation_id" in blank_install.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None
    assert config.remote_installation_id is None


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
    assert config.remote_installation_id is None


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
        captured["installation_id"] = submission.installation_id
        captured["payload_keys"] = sorted(submission.envelope.payload.keys())
        captured["intake_url"] = config.intake_url
        from driftshield.intake_contract import IntakeSubmissionResponse

        return IntakeSubmissionResponse(submission_id="sub_xyz", processing_status="received")

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "sub_xyz" in result.stdout
    assert "received" in result.stdout
    assert captured["installation_id"] == _OSS_TEST_INSTALLATION_ID
    assert captured["intake_url"] == _OSS_TEST_INTAKE_URL
    assert "prompts" not in captured["payload_keys"]
    assert "responses" not in captured["payload_keys"]
    assert "user_identifiers" not in captured["payload_keys"]
    assert "metadata" in captured["payload_keys"]


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


def test_submit_session_surfaces_remote_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    from driftshield.remote_submission import RemoteSubmissionError

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        raise RemoteSubmissionError("intake HTTP 401: invalid_installation_credentials")

    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.post_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "401" in result.stdout
    assert "invalid_installation_credentials" in result.stdout
