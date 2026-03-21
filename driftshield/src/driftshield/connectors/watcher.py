from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from driftshield.connectors.registry import SessionInfo, get_connector_adapter
from driftshield.db.ingest_service import TranscriptIngestService
from driftshield.db.models import ConnectorModel, ConnectorSessionStateModel

_WATCH_ELIGIBLE_CONSENT_STATES = {"approved_always"}
_DISABLED_STATUSES = {"denied", "disconnected"}


@dataclass(frozen=True)
class WatchCycleResult:
    connectors_seen: int = 0
    connectors_processed: int = 0
    sessions_seen: int = 0
    sessions_ingested: int = 0


class ConnectorWatchService:
    def __init__(self, session_factory: sessionmaker, *, poll_interval_seconds: float = 5.0):
        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds

    def run_once(self) -> WatchCycleResult:
        return self._run_cycle(keep_running_status=False)

    def run_forever(self) -> None:
        try:
            while True:
                self._run_cycle(keep_running_status=True)
                time.sleep(self._poll_interval_seconds)
        except KeyboardInterrupt:
            self._reset_running_connectors()
            raise

    def _run_cycle(self, *, keep_running_status: bool) -> WatchCycleResult:
        with self._session_factory() as db:
            connector_ids = [
                connector.id
                for connector in db.query(ConnectorModel)
                .order_by(ConnectorModel.display_name.asc(), ConnectorModel.root_path.asc())
                .all()
            ]

        result = WatchCycleResult(connectors_seen=len(connector_ids))
        for connector_id in connector_ids:
            with self._session_factory() as db:
                connector = db.get(ConnectorModel, connector_id)
                if connector is None:
                    continue

                if self._is_disabled(connector):
                    connector.watch_status = self._default_watch_status(connector)
                    connector.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    continue

                if connector.status == "paused":
                    connector.watch_status = "paused"
                    connector.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    continue

                try:
                    outcome = self._process_connector(
                        db=db,
                        connector=connector,
                        keep_running_status=keep_running_status,
                    )
                except Exception as exc:
                    now = datetime.now(timezone.utc)
                    connector.watch_status = "error"
                    connector.last_error = str(exc)
                    connector.last_error_at = now
                    connector.last_watch_heartbeat_at = now
                    connector.updated_at = now
                    db.commit()
                    continue

                result = WatchCycleResult(
                    connectors_seen=result.connectors_seen,
                    connectors_processed=result.connectors_processed + 1,
                    sessions_seen=result.sessions_seen + outcome.sessions_seen,
                    sessions_ingested=result.sessions_ingested + outcome.sessions_ingested,
                )
                db.commit()

        return result

    def _process_connector(
        self,
        *,
        db,
        connector: ConnectorModel,
        keep_running_status: bool,
    ) -> WatchCycleResult:
        now = datetime.now(timezone.utc)
        adapter = get_connector_adapter(connector.source_type)
        sessions = adapter.scan(Path(connector.root_path))
        session_states = {
            state.source_path: state
            for state in (
                db.query(ConnectorSessionStateModel)
                .filter(ConnectorSessionStateModel.connector_id == connector.id)
                .all()
            )
        }

        connector.last_scanned_at = now
        connector.last_watch_heartbeat_at = now
        connector.last_seen_activity_at = sessions[0].modified_at if sessions else None
        connector.watch_status = "running"

        ingest_service = TranscriptIngestService(db)
        ingested = 0
        last_ingested_source_session_id: str | None = None
        last_ingested_source_path: str | None = None

        for session_info in sorted(sessions, key=lambda item: (item.modified_at, item.path)):
            state = session_states.get(str(session_info.path))
            changed, transcript_hash = self._session_changed(
                state=state,
                session_info=session_info,
            )
            if not changed:
                if state is not None:
                    state.last_modified_at = session_info.modified_at
                    state.last_size_bytes = session_info.size_bytes
                    state.last_activity_at = session_info.modified_at
                    state.updated_at = now
                continue

            raw_bytes = session_info.path.read_bytes()
            transcript_hash = hashlib.sha256(raw_bytes).hexdigest()
            outcome = ingest_service.ingest_bytes(
                raw_bytes=raw_bytes,
                parser_name=connector.parser_name,
                source_path=str(session_info.path),
                existing_session_id=state.session_model_id if state is not None else None,
            )
            state = self._update_session_state(
                db=db,
                connector=connector,
                state=state,
                session_info=session_info,
                transcript_hash=transcript_hash,
                session_model_id=outcome.session_id,
                now=now,
            )
            session_states[state.source_path] = state
            ingested += 1
            last_ingested_source_session_id = session_info.session_id
            last_ingested_source_path = str(session_info.path)

        connector.watch_status = "running" if keep_running_status else self._default_watch_status(connector)
        connector.last_error = None
        connector.last_error_at = None
        connector.updated_at = now
        connector.metadata_json = {
            **(connector.metadata_json or {}),
            "path_exists": Path(connector.root_path).exists(),
            "session_count": len(sessions),
            "tracked_session_count": len(session_states),
            "ingested_session_count": sum(
                1 for state in session_states.values() if state.session_model_id is not None
            ),
            "newest_session_id": sessions[0].session_id if sessions else None,
            "newest_session_path": str(sessions[0].path) if sessions else None,
            "last_ingested_source_session_id": last_ingested_source_session_id,
            "last_ingested_source_path": last_ingested_source_path,
        }
        if ingested > 0:
            connector.last_ingested_at = now

        return WatchCycleResult(
            connectors_seen=1,
            connectors_processed=1,
            sessions_seen=len(sessions),
            sessions_ingested=ingested,
        )

    def _session_changed(
        self,
        *,
        state: ConnectorSessionStateModel | None,
        session_info: SessionInfo,
    ) -> tuple[bool, str | None]:
        if state is None:
            return True, None

        if (
            state.last_modified_at == session_info.modified_at
            and state.last_size_bytes == session_info.size_bytes
        ):
            return False, state.last_transcript_hash

        raw_bytes = session_info.path.read_bytes()
        transcript_hash = hashlib.sha256(raw_bytes).hexdigest()
        if state.last_transcript_hash == transcript_hash:
            return False, transcript_hash
        return True, transcript_hash

    def _update_session_state(
        self,
        *,
        db,
        connector: ConnectorModel,
        state: ConnectorSessionStateModel | None,
        session_info: SessionInfo,
        transcript_hash: str,
        session_model_id: uuid.UUID,
        now: datetime,
    ) -> ConnectorSessionStateModel:
        if state is None:
            state = ConnectorSessionStateModel(
                connector_id=connector.id,
                source_session_id=session_info.session_id,
                source_path=str(session_info.path),
                parser_name=connector.parser_name,
                session_model_id=session_model_id,
                created_at=now,
                updated_at=now,
            )
            db.add(state)

        state.source_session_id = session_info.session_id
        state.source_path = str(session_info.path)
        state.parser_name = connector.parser_name
        state.session_model_id = session_model_id
        state.last_modified_at = session_info.modified_at
        state.last_size_bytes = session_info.size_bytes
        state.last_transcript_hash = transcript_hash
        state.last_activity_at = session_info.modified_at
        state.last_ingested_at = now
        state.last_error = None
        state.last_error_at = None
        state.updated_at = now
        return state

    def _reset_running_connectors(self) -> None:
        with self._session_factory() as db:
            for connector in (
                db.query(ConnectorModel)
                .filter(ConnectorModel.watch_status == "running")
                .all()
            ):
                connector.watch_status = self._default_watch_status(connector)
                connector.updated_at = datetime.now(timezone.utc)
            db.commit()

    def _is_disabled(self, connector: ConnectorModel) -> bool:
        if not connector.watchable:
            return True
        if connector.status in _DISABLED_STATUSES:
            return True
        return connector.consent_state not in _WATCH_ELIGIBLE_CONSENT_STATES

    def _default_watch_status(self, connector: ConnectorModel) -> str:
        if connector.status == "paused":
            return "paused"
        if self._is_disabled(connector):
            return "disabled"
        return "idle"
