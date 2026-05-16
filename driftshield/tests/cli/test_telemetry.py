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


def test_status_default_shows_remote_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is False
    assert payload["remote_intake_url"] is None
    assert payload["remote_api_key_configured"] is False


def test_remote_enable_persists_config_and_redacts_key_in_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            _OSS_TEST_API_KEY,
        ],
    )
    assert enabled.exit_code == 0
    assert _OSS_TEST_API_KEY not in enabled.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.remote_api_key == _OSS_TEST_API_KEY

    status = runner.invoke(app, ["telemetry", "status", "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is True
    assert payload["remote_intake_url"] == _OSS_TEST_INTAKE_URL
    assert payload["remote_api_key_configured"] is True
    assert "remote_api_key" not in payload
    assert _OSS_TEST_API_KEY not in status.stdout


def test_remote_disable_clears_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            _OSS_TEST_API_KEY,
        ],
    )

    disabled = runner.invoke(app, ["telemetry", "remote-disable"])
    assert disabled.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None


def test_remote_enable_rejects_empty_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    blank_url = runner.invoke(
        app,
        ["telemetry", "remote-enable", "--intake-url", "   ", "--api-key", _OSS_TEST_API_KEY],
    )
    assert blank_url.exit_code == 1
    assert "intake_url" in blank_url.stdout

    blank_key = runner.invoke(
        app,
        ["telemetry", "remote-enable", "--intake-url", _OSS_TEST_INTAKE_URL, "--api-key", "   "],
    )
    assert blank_key.exit_code == 1
    assert "api_key" in blank_key.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None


def test_local_capture_unchanged_when_remote_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            _OSS_TEST_API_KEY,
        ],
    )
    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 0

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration", "heartbeat"]

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL


def test_remote_enable_does_not_toggle_local_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            _OSS_TEST_API_KEY,
        ],
    )
    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.enabled is False
    assert config.install_id is None


def test_remote_disable_does_not_clear_local_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            _OSS_TEST_API_KEY,
        ],
    )

    install_id_before = TelemetryService().load_config().install_id
    runner.invoke(app, ["telemetry", "remote-disable"])

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.install_id == install_id_before
    assert config.remote_intake_url is None
