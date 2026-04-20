"""CLI commands for consent-gated Phase 2a telemetry."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from driftshield.telemetry import TelemetryService, validate_outcome_status

console = Console(force_terminal=True)
app = typer.Typer(help="Manage opt-in Phase 2a telemetry.")


@app.command("status")
def telemetry_status(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show telemetry consent and heartbeat status."""
    config = TelemetryService().load_config()
    payload = {
        "enabled": config.enabled,
        "install_id": config.install_id,
        "registered_at": config.registered_at,
        "last_heartbeat_at": config.last_heartbeat_at,
        "event_stream_path": config.event_stream_path,
    }
    if json_output:
        typer.echo(json.dumps(payload))
        return

    console.print(json.dumps(payload, indent=2))


@app.command("enable")
def telemetry_enable() -> None:
    """Enable telemetry and register this local installation."""
    config = TelemetryService().enable()
    console.print(
        f"Telemetry enabled for install {config.install_id}. Event stream: {config.event_stream_path}"
    )


@app.command("disable")
def telemetry_disable() -> None:
    """Disable telemetry emission."""
    config = TelemetryService().disable()
    console.print(
        f"Telemetry disabled. Existing install id remains {config.install_id or 'unset'}."
    )


@app.command("heartbeat")
def telemetry_heartbeat() -> None:
    """Emit one heartbeat event when telemetry opt-in is enabled."""
    emitted = TelemetryService().heartbeat()
    if not emitted:
        console.print("Telemetry is disabled; heartbeat not emitted.")
        raise typer.Exit(1)
    console.print("Heartbeat emitted.")


@app.command("emit-analysis")
def telemetry_emit_analysis(
    outcome_status: str = typer.Option(..., "--outcome-status", help="matched, unclassified, or not_classifiable"),
    match_count: int = typer.Option(0, "--match-count", min=0),
    primary_family_id: str | None = typer.Option(None, "--primary-family-id"),
    mixed_family: bool = typer.Option(False, "--mixed-family"),
    not_classifiable_reason: str | None = typer.Option(None, "--not-classifiable-reason"),
) -> None:
    """Emit one sample analysis-result telemetry event for smoke testing."""
    try:
        validated_outcome_status = validate_outcome_status(outcome_status)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    emitted = TelemetryService().record_analysis_event(
        outcome_status=validated_outcome_status,
        match_count=match_count,
        primary_family_id=primary_family_id,
        mixed_family=mixed_family,
        not_classifiable_reason=not_classifiable_reason,
    )
    if not emitted:
        console.print("Telemetry is disabled; analysis event not emitted.")
        raise typer.Exit(1)
    console.print("Analysis event emitted.")
