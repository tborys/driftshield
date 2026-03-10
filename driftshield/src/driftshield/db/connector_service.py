from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from driftshield.connectors.registry import (
    ConnectorScanResult,
    DiscoveryContext,
    discover_connector_candidates,
    get_connector_adapter,
)
from driftshield.db.models import ConnectorModel

_APPROVED_CONSENT_STATES = {"approved_once", "approved_always"}
_BLOCKED_STATUSES = {"denied", "disconnected", "paused"}


class ConnectorService:
    def __init__(self, db: DBSession):
        self._db = db

    def refresh_candidates(
        self,
        *,
        project_dir: Path,
        claude_home: Path | None = None,
        codex_home: Path | None = None,
    ) -> list[ConnectorModel]:
        now = datetime.now(timezone.utc)
        context = DiscoveryContext(
            project_dir=project_dir.resolve(),
            claude_home=claude_home,
            codex_home=codex_home,
        )
        for candidate in discover_connector_candidates(context):
            connector = self._db.query(ConnectorModel).filter(
                ConnectorModel.connector_key == candidate.connector_key
            ).one_or_none()
            metadata = {
                **candidate.metadata,
                "path_exists": candidate.root_path.exists(),
            }

            if connector is None:
                connector = ConnectorModel(
                    connector_key=candidate.connector_key,
                    source_type=candidate.source_type,
                    display_name=candidate.display_name,
                    root_path=str(candidate.root_path),
                    parser_name=candidate.parser_name,
                    consent_state="pending",
                    status="proposed",
                    watchable=candidate.watchable,
                    metadata_json=metadata,
                    created_at=now,
                    updated_at=now,
                )
                self._db.add(connector)
                self._db.flush()
                continue

            connector.display_name = candidate.display_name
            connector.root_path = str(candidate.root_path)
            connector.parser_name = candidate.parser_name
            connector.watchable = candidate.watchable
            connector.metadata_json = {
                **(connector.metadata_json or {}),
                **metadata,
            }
            connector.updated_at = now

        self._db.flush()
        return self.list_connectors()

    def list_connectors(self) -> list[ConnectorModel]:
        return self._db.query(ConnectorModel).order_by(
            ConnectorModel.display_name.asc(),
            ConnectorModel.root_path.asc(),
        ).all()

    def get_connector(self, connector_id: uuid.UUID) -> ConnectorModel | None:
        return self._db.get(ConnectorModel, connector_id)

    def approve_connector(self, connector_id: uuid.UUID, *, mode: str) -> ConnectorModel:
        connector = self._require_connector(connector_id)
        if mode not in {"once", "always"}:
            raise ValueError("mode must be once or always")

        connector.consent_state = "approved_always" if mode == "always" else "approved_once"
        connector.status = "ready"
        connector.last_error = None
        connector.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        return connector

    def deny_connector(self, connector_id: uuid.UUID) -> ConnectorModel:
        connector = self._require_connector(connector_id)
        connector.consent_state = "denied"
        connector.status = "denied"
        connector.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        return connector

    def pause_connector(self, connector_id: uuid.UUID) -> ConnectorModel:
        connector = self._require_connector(connector_id)
        connector.status = "paused"
        connector.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        return connector

    def disconnect_connector(self, connector_id: uuid.UUID) -> ConnectorModel:
        connector = self._require_connector(connector_id)
        connector.consent_state = "pending"
        connector.status = "disconnected"
        connector.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        return connector

    def rescan_connector(self, connector_id: uuid.UUID) -> ConnectorScanResult:
        connector = self._require_connector(connector_id)
        self._assert_scan_allowed(connector)

        try:
            adapter = get_connector_adapter(connector.source_type)
            sessions = adapter.scan(Path(connector.root_path))
        except Exception as exc:
            connector.status = "error"
            connector.last_error = str(exc)
            connector.updated_at = datetime.now(timezone.utc)
            self._db.flush()
            raise

        now = datetime.now(timezone.utc)
        newest = sessions[0] if sessions else None
        connector.last_scanned_at = now
        connector.last_seen_activity_at = newest.modified_at if newest else None
        connector.last_error = None
        connector.metadata_json = {
            **(connector.metadata_json or {}),
            "path_exists": Path(connector.root_path).exists(),
            "session_count": len(sessions),
            "newest_session_id": newest.session_id if newest else None,
            "newest_session_path": str(newest.path) if newest else None,
        }
        if connector.consent_state == "approved_once":
            connector.consent_state = "pending"
            connector.status = "proposed"
        else:
            connector.status = "ready"
        connector.updated_at = now
        self._db.flush()

        return ConnectorScanResult(
            connector_id=str(connector.id),
            session_count=len(sessions),
            newest_session_id=newest.session_id if newest else None,
            newest_session_path=str(newest.path) if newest else None,
            newest_modified_at=newest.modified_at if newest else None,
            sessions=sessions,
        )

    def _require_connector(self, connector_id: uuid.UUID) -> ConnectorModel:
        connector = self.get_connector(connector_id)
        if connector is None:
            raise LookupError("Connector not found")
        return connector

    def _assert_scan_allowed(self, connector: ConnectorModel) -> None:
        if connector.status in _BLOCKED_STATUSES:
            raise ValueError(f"Connector is {connector.status} and cannot be scanned")
        if connector.consent_state not in _APPROVED_CONSENT_STATES:
            raise ValueError("Connector requires explicit approval before scanning")
