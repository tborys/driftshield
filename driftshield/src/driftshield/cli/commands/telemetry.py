"""CLI commands for consent-gated Phase 2a telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.remote_submission import (
    RemoteSubmissionConfig,
    RemoteSubmissionError,
    build_intake_request,
    post_submission,
)
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
        "remote_enabled": (
            config.remote_intake_url is not None
            and config.remote_api_key is not None
            and config.remote_installation_id is not None
        ),
        "remote_intake_url": config.remote_intake_url,
        "remote_installation_id": config.remote_installation_id,
        "remote_api_key_configured": config.remote_api_key is not None,
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


@app.command("remote-enable")
def telemetry_remote_enable(
    intake_url: str = typer.Option(..., "--intake-url", help="Intake API URL the OSS submission envelope will POST to."),
    api_key: str = typer.Option(..., "--api-key", help="API key for the configured intake URL."),
    installation_id: str = typer.Option(..., "--installation-id", help="Installation identifier registered with the intake server."),
) -> None:
    """Persist remote intake configuration for OSS submission. Does not send anything."""
    try:
        config = TelemetryService().remote_enable(
            intake_url=intake_url,
            api_key=api_key,
            installation_id=installation_id,
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"Remote submission configured. Intake URL: {config.remote_intake_url}. "
        f"Installation: {config.remote_installation_id}. "
        "API key stored locally; not displayed."
    )


@app.command("remote-disable")
def telemetry_remote_disable() -> None:
    """Clear remote intake configuration. Local telemetry capture is unaffected."""
    TelemetryService().remote_disable()
    console.print("Remote submission configuration cleared.")


@app.command("submit-session")
def telemetry_submit_session(
    path: Path = typer.Option(..., "--path", help="JSON file with the finished session payload."),
    source_session_id: str | None = typer.Option(
        None,
        "--source-session-id",
        help="Override the source_session_id field. Defaults to the JSON file stem.",
    ),
    workflow_reference: str | None = typer.Option(
        None, "--workflow-reference", help="Optional workflow identifier."
    ),
    project_reference: str | None = typer.Option(
        None, "--project-reference", help="Optional project identifier."
    ),
    source_report_id: str | None = typer.Option(
        None, "--source-report-id", help="Optional source report identifier."
    ),
) -> None:
    """Build a phase3f.v1 envelope from a finished session JSON and POST once to the configured intake URL."""
    config = TelemetryService().load_config()
    if not config.remote_intake_url or not config.remote_api_key or not config.remote_installation_id:
        console.print(
            "[red]Error:[/red] Remote submission is not configured. "
            "Run `driftshield telemetry remote-enable` first."
        )
        raise typer.Exit(1)

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]Error:[/red] Could not read session file: {exc}")
        raise typer.Exit(1) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error:[/red] Session file is not valid JSON: {exc}")
        raise typer.Exit(1) from exc
    if not isinstance(payload, dict):
        console.print("[red]Error:[/red] Session file must contain a JSON object at top level.")
        raise typer.Exit(1)

    submission = build_intake_request(
        installation_id=config.remote_installation_id,
        source_session_id=source_session_id or path.stem,
        payload=payload,
        workflow_reference=workflow_reference,
        project_reference=project_reference,
        source_report_id=source_report_id,
    )

    submission_config = RemoteSubmissionConfig(
        intake_url=config.remote_intake_url,
        api_key=config.remote_api_key,
        installation_id=config.remote_installation_id,
    )
    try:
        response = post_submission(config=submission_config, submission=submission)
    except RemoteSubmissionError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(
        f"Submitted. submission_id={response.submission_id} status={response.processing_status}"
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
    primary_mechanism_id: str | None = typer.Option(None, "--primary-mechanism-id"),
    mixed_mechanism: bool = typer.Option(False, "--mixed-mechanism"),
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
        primary_mechanism_id=primary_mechanism_id,
        mixed_mechanism=mixed_mechanism,
        not_classifiable_reason=not_classifiable_reason,
    )
    if not emitted:
        console.print("Telemetry is disabled; analysis event not emitted.")
        raise typer.Exit(1)
    console.print("Analysis event emitted.")
