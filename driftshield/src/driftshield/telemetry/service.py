"""Consent-gated local telemetry transport for the Phase 2a evidence loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import uuid
from typing import Any


@dataclass(slots=True)
class TelemetryConfig:
    enabled: bool = False
    install_id: str | None = None
    registered_at: str | None = None
    last_heartbeat_at: str | None = None
    event_stream_path: str | None = None


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event_type: str
    occurred_at: str
    install_id: str
    payload: dict[str, Any]


class TelemetryService:
    """Persist opt-in telemetry events to a local event stream."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or _telemetry_home()
        self._config_path = self._home / "config.json"
        self._default_stream_path = self._home / "events.ndjson"

    def load_config(self) -> TelemetryConfig:
        if not self._config_path.exists():
            return TelemetryConfig(event_stream_path=str(self._default_stream_path))

        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return TelemetryConfig(
            enabled=bool(data.get("enabled", False)),
            install_id=_optional_string(data.get("install_id")),
            registered_at=_optional_string(data.get("registered_at")),
            last_heartbeat_at=_optional_string(data.get("last_heartbeat_at")),
            event_stream_path=_optional_string(data.get("event_stream_path"))
            or str(self._default_stream_path),
        )

    def enable(self) -> TelemetryConfig:
        config = self.load_config()
        changed = False
        if not config.install_id:
            config.install_id = str(uuid.uuid4())
            changed = True
        if not config.event_stream_path:
            config.event_stream_path = str(self._default_stream_path)
            changed = True
        if not config.enabled:
            config.enabled = True
            changed = True
        if not config.registered_at:
            timestamp = _utc_now().isoformat()
            config.registered_at = timestamp
            changed = True
            self._write_event(
                TelemetryEvent(
                    event_type="registration",
                    occurred_at=timestamp,
                    install_id=config.install_id,
                    payload={
                        "consent_state": "opted_in",
                        "event_inventory_version": "phase-2a-v1",
                    },
                ),
                config=config,
            )
        if changed:
            self._save_config(config)
        return config

    def disable(self) -> TelemetryConfig:
        config = self.load_config()
        config.enabled = False
        if not config.event_stream_path:
            config.event_stream_path = str(self._default_stream_path)
        self._save_config(config)
        return config

    def heartbeat(self) -> bool:
        config = self.load_config()
        if not config.enabled or not config.install_id:
            return False
        timestamp = _utc_now().isoformat()
        config.last_heartbeat_at = timestamp
        self._write_event(
            TelemetryEvent(
                event_type="heartbeat",
                occurred_at=timestamp,
                install_id=config.install_id,
                payload={"status": "alive", "event_inventory_version": "phase-2a-v1"},
            ),
            config=config,
        )
        self._save_config(config)
        return True

    def record_analysis_event(
        self,
        *,
        outcome_status: str,
        match_count: int,
        primary_family_id: str | None = None,
        mixed_family: bool = False,
        not_classifiable_reason: str | None = None,
    ) -> bool:
        config = self.load_config()
        if not config.enabled or not config.install_id:
            return False
        self._write_event(
            TelemetryEvent(
                event_type="analysis_result",
                occurred_at=_utc_now().isoformat(),
                install_id=config.install_id,
                payload={
                    "outcome_status": outcome_status,
                    "classifiable": outcome_status in {"matched", "unclassified"},
                    "match_count": match_count,
                    "primary_family_id": primary_family_id,
                    "mixed_family": mixed_family,
                    "not_classifiable_reason": not_classifiable_reason,
                    "event_inventory_version": "phase-2a-v1",
                },
            ),
            config=config,
        )
        return True

    def read_events(self) -> list[dict[str, Any]]:
        config = self.load_config()
        stream_path = Path(config.event_stream_path or self._default_stream_path)
        if not stream_path.exists():
            return []
        return [json.loads(line) for line in stream_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _save_config(self, config: TelemetryConfig) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")

    def _write_event(self, event: TelemetryEvent, *, config: TelemetryConfig) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        stream_path = Path(config.event_stream_path or self._default_stream_path)
        stream_path.parent.mkdir(parents=True, exist_ok=True)
        with stream_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")


def _telemetry_home() -> Path:
    configured = os.environ.get("DRIFTSHIELD_HOME")
    if configured:
        return Path(configured).expanduser() / "telemetry"
    return Path.home() / ".driftshield" / "telemetry"


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected string value")
    stripped = value.strip()
    return stripped or None


def _utc_now() -> datetime:
    return datetime.now(UTC)
