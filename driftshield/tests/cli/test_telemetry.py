from __future__ import annotations

import json
from pathlib import Path

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
