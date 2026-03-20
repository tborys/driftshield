from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import (
    ConnectorApproveRequest,
    ConnectorDiscoverRequest,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorScanResponse,
)
from driftshield.db.connector_service import ConnectorService
from driftshield.db.models import ConnectorModel

router = APIRouter()


def _claude_home_from_env() -> Path | None:
    value = os.environ.get("CLAUDE_HOME")
    return Path(value).expanduser() if value else None


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _connector_response(connector: ConnectorModel) -> ConnectorResponse:
    return ConnectorResponse(
        id=connector.id,
        source_type=connector.source_type,
        display_name=connector.display_name,
        root_path=connector.root_path,
        parser_name=connector.parser_name,
        consent_state=connector.consent_state,
        status=connector.status,
        watchable=connector.watchable,
        metadata=connector.metadata_json or {},
        last_scanned_at=_ensure_utc(connector.last_scanned_at),
        last_seen_activity_at=_ensure_utc(connector.last_seen_activity_at),
        last_error=connector.last_error,
    )


@router.get("/api/connectors", response_model=ConnectorListResponse)
def list_connectors(
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    return ConnectorListResponse(
        items=[_connector_response(connector) for connector in service.list_connectors()]
    )


@router.post("/api/connectors/discover", response_model=ConnectorListResponse)
def discover_connectors(
    payload: ConnectorDiscoverRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    project_dir = Path(payload.project_dir).expanduser().resolve() if payload.project_dir else Path.cwd()
    connectors = service.refresh_candidates(
        project_dir=project_dir,
        claude_home=_claude_home_from_env(),
    )
    db.commit()
    return ConnectorListResponse(items=[_connector_response(connector) for connector in connectors])


@router.get("/api/connectors/{connector_id}", response_model=ConnectorResponse)
def get_connector(
    connector_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    connector = service.get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return _connector_response(connector)


@router.post("/api/connectors/{connector_id}/approve", response_model=ConnectorResponse)
def approve_connector(
    connector_id: uuid.UUID,
    payload: ConnectorApproveRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    try:
        connector = service.approve_connector(connector_id, mode=payload.mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _connector_response(connector)


@router.post("/api/connectors/{connector_id}/deny", response_model=ConnectorResponse)
def deny_connector(
    connector_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    try:
        connector = service.deny_connector(connector_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return _connector_response(connector)


@router.post("/api/connectors/{connector_id}/pause", response_model=ConnectorResponse)
def pause_connector(
    connector_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    try:
        connector = service.pause_connector(connector_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return _connector_response(connector)


@router.post("/api/connectors/{connector_id}/disconnect", response_model=ConnectorResponse)
def disconnect_connector(
    connector_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    try:
        connector = service.disconnect_connector(connector_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return _connector_response(connector)


@router.post("/api/connectors/{connector_id}/rescan", response_model=ConnectorScanResponse)
def rescan_connector(
    connector_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    service = ConnectorService(db)
    try:
        scan = service.rescan_connector(connector_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ConnectorScanResponse(
        connector_id=uuid.UUID(scan.connector_id),
        session_count=scan.session_count,
        newest_session_id=scan.newest_session_id,
        newest_session_path=scan.newest_session_path,
        newest_modified_at=_ensure_utc(scan.newest_modified_at),
    )
