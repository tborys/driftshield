"""CLI commands for local connector discovery and consent-gated scans."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console

from driftshield.db.connector_service import ConnectorService
from driftshield.db.engine import get_engine, get_session_factory
from driftshield.db.models import Base, ConnectorModel

console = Console()
app = typer.Typer(help="Manage local transcript connectors.")


def _claude_home_from_env() -> Path | None:
    value = os.environ.get("CLAUDE_HOME")
    return Path(value).expanduser() if value else None


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _connector_payload(connector: ConnectorModel) -> dict[str, object]:
    return {
        "id": str(connector.id),
        "source_type": connector.source_type,
        "display_name": connector.display_name,
        "root_path": connector.root_path,
        "parser_name": connector.parser_name,
        "consent_state": connector.consent_state,
        "status": connector.status,
        "watchable": connector.watchable,
        "metadata": connector.metadata_json or {},
        "last_scanned_at": (
            _ensure_utc(connector.last_scanned_at).isoformat()
            if connector.last_scanned_at
            else None
        ),
        "last_seen_activity_at": (
            _ensure_utc(connector.last_seen_activity_at).isoformat()
            if connector.last_seen_activity_at
            else None
        ),
        "last_error": connector.last_error,
    }


def _open_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    return session_factory()


@app.command("discover")
def discover_connectors(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", help="Workspace to anchor discovery."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Persist proposed connectors without scanning them."""
    with _open_db() as db:
        service = ConnectorService(db)
        connectors = service.refresh_candidates(
            project_dir=project_dir,
            claude_home=_claude_home_from_env(),
        )
        db.commit()

    payload = [_connector_payload(connector) for connector in connectors]
    if json_output:
        typer.echo(json.dumps(payload))
        return

    if not payload:
        console.print("No connector candidates found.")
        return

    for connector in payload:
        console.print(
            f"{connector['id']} {connector['display_name']} "
            f"[dim]{connector['status']} / {connector['consent_state']}[/dim]"
        )


@app.command("list")
def list_connectors(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """List saved connectors."""
    with _open_db() as db:
        connectors = ConnectorService(db).list_connectors()

    payload = [_connector_payload(connector) for connector in connectors]
    if json_output:
        typer.echo(json.dumps(payload))
        return

    if not payload:
        console.print("No connectors saved.")
        return

    for connector in payload:
        console.print(
            f"{connector['id']} {connector['display_name']} "
            f"[dim]{connector['status']} / {connector['consent_state']}[/dim]"
        )


@app.command("status")
def connector_status(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show connector details."""
    with _open_db() as db:
        connector = ConnectorService(db).get_connector(connector_id)

    if connector is None:
        console.print("[red]Error:[/red] Connector not found.")
        raise typer.Exit(1)

    payload = _connector_payload(connector)
    if json_output:
        typer.echo(json.dumps(payload))
        return

    console.print(json.dumps(payload, indent=2))


@app.command("approve")
def approve_connector(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
    always: bool = typer.Option(False, "--always", help="Keep consent for future rescans."),
) -> None:
    """Approve a connector scan once or always."""
    mode = "always" if always else "once"
    with _open_db() as db:
        service = ConnectorService(db)
        try:
            connector = service.approve_connector(connector_id, mode=mode)
        except (LookupError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        db.commit()

    console.print(
        f"Approved {connector.display_name} ({connector.id}) with {connector.consent_state}."
    )


@app.command("deny")
def deny_connector(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
) -> None:
    """Deny a connector scan request."""
    with _open_db() as db:
        service = ConnectorService(db)
        try:
            connector = service.deny_connector(connector_id)
        except LookupError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        db.commit()

    console.print(f"Denied {connector.display_name} ({connector.id}).")


@app.command("pause")
def pause_connector(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
) -> None:
    """Pause a saved connector."""
    with _open_db() as db:
        service = ConnectorService(db)
        try:
            connector = service.pause_connector(connector_id)
        except LookupError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        db.commit()

    console.print(f"Paused {connector.display_name} ({connector.id}).")


@app.command("disconnect")
def disconnect_connector(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
) -> None:
    """Disconnect a saved connector and clear active consent."""
    with _open_db() as db:
        service = ConnectorService(db)
        try:
            connector = service.disconnect_connector(connector_id)
        except LookupError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        db.commit()

    console.print(f"Disconnected {connector.display_name} ({connector.id}).")


@app.command("rescan")
def rescan_connector(
    connector_id: uuid.UUID = typer.Argument(..., help="Connector identifier."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Rescan an approved connector."""
    with _open_db() as db:
        service = ConnectorService(db)
        try:
            scan = service.rescan_connector(connector_id)
        except (LookupError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        db.commit()

    payload = {
        "connector_id": scan.connector_id,
        "session_count": scan.session_count,
        "newest_session_id": scan.newest_session_id,
        "newest_session_path": scan.newest_session_path,
        "newest_modified_at": (
            _ensure_utc(scan.newest_modified_at).isoformat() if scan.newest_modified_at else None
        ),
    }
    if json_output:
        typer.echo(json.dumps(payload))
        return

    console.print(
        f"Rescanned {scan.connector_id}: {scan.session_count} session(s), "
        f"latest={scan.newest_session_id or 'none'}."
    )
