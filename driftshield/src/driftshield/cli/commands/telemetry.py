"""CLI commands for consent-gated telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.cli._submit import run_submit
from driftshield.telemetry import (
    TelemetryService,
    effective_oss_intake_url,
    validate_outcome_status,
)

console = Console(force_terminal=True)
app = typer.Typer(help="Manage opt-in telemetry.")


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
        "remote_enabled": config.remote_intake_url is not None,
        "remote_intake_url": config.remote_intake_url,
        "remote_opt_out": config.remote_opt_out,
        # The URL an OSS-lane submission will actually use right now: the
        # configured override, the baked community default, or null after
        # remote-disable.
        "effective_oss_intake_url": effective_oss_intake_url(config),
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
) -> None:
    """Persist the OSS intake URL. No keys needed; the OSS lane is unauthenticated."""
    try:
        config = TelemetryService().remote_enable(intake_url=intake_url)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"Remote submission configured. Intake URL: {config.remote_intake_url}."
    )


@app.command("remote-disable")
def telemetry_remote_disable() -> None:
    """Opt out of remote submission entirely. Local telemetry capture is unaffected."""
    TelemetryService().remote_disable()
    console.print(
        "Remote submission disabled. The baked community default no longer "
        "applies; run `telemetry remote-enable` to re-enable."
    )


@app.command("submit-session", hidden=True)
def telemetry_submit_session(
    path: Path = typer.Option(..., "--path", help="JSON file with the finished session payload."),
    source_session_id: str | None = typer.Option(
        None,
        "--source-session-id",
        help="Override the source_session_id field. Defaults to the JSON file stem.",
    ),
    workflow_reference: str | None = typer.Option(
        None,
        "--workflow-reference",
        help=(
            "Workflow identifier stamped on the envelope. Defaults to the "
            "value in the session JSON's 'workflow_reference' field, or "
            "'default' if neither is supplied."
        ),
    ),
    project_reference: str | None = typer.Option(
        None, "--project-reference", help="Optional project identifier."
    ),
    source_report_id: str | None = typer.Option(
        None, "--source-report-id", help="Optional source report identifier."
    ),
    agent_id: str | None = typer.Option(
        None, "--agent-id", help="Optional agent identifier recorded as run provenance."
    ),
    model_name: str | None = typer.Option(
        None, "--model-name", help="Optional model name recorded as run provenance."
    ),
    model_version: str | None = typer.Option(
        None, "--model-version", help="Optional model version recorded as run provenance."
    ),
    dry_run_redaction: bool = typer.Option(
        False,
        "--dry-run-redaction",
        help="Run the recursive redactor, print the redaction entries, exit without submitting.",
    ),
    show_manifest: bool = typer.Option(
        False,
        "--show-manifest",
        help="Print the redaction manifest that would accompany the submission, exit without submitting.",
    ),
    force_unknown_shape: bool = typer.Option(
        False,
        "--force-unknown-shape",
        help="Submit even if the transcript top-level shape is not recognised by the redactor.",
    ),
    include_analysis: bool = typer.Option(
        False,
        "--include-analysis",
        help=(
            "Run the local deterministic matcher and attach a signature_summary "
            "block to the envelope. Off by default; no behavioural change vs the "
            "default submission path when omitted."
        ),
    ),
    tier: str = typer.Option(
        "oss",
        "--tier",
        help=(
            "Submission tier: 'oss' (unauthenticated community lane) or "
            "'teams' (authenticated; requires DRIFTSHIELD_API_KEY). Large "
            "transcripts upload via presigned storage on either tier."
        ),
    ),
    environment: str | None = typer.Option(
        None,
        "--environment",
        help=(
            "Declared run environment for the community (oss) lane: "
            "production, staging, test, or demo. Community opt-in declares "
            "production by default; pass this only for the uncommon "
            "non-production contribution."
        ),
    ),
) -> None:
    """Build a phase3g.v1 envelope from a finished session JSON and POST once to the OSS intake URL.

    The OSS lane is unauthenticated. No X-API-Key header is sent, no installation_id
    or consent_state is included in the request. The server binds the persisted row
    to the in-stack OSS fallback installation + consent. When no intake URL is
    configured, the OSS lane submits to the baked-in community intake URL, so
    community opt-in needs no prior ``remote-enable``. An explicit
    ``telemetry remote-disable`` opts out of the baked default too.

    Community opt-in is the act of declaring the run real: on the oss lane the
    declared environment defaults to ``production`` unless the session JSON or
    ``--environment`` says otherwise. The server records it as a
    submitter-declared value; the server itself never defaults to production.

    ``workflow_reference`` precedence: --workflow-reference flag, then
    session JSON's ``workflow_reference`` field, then ``"default"``. Distinct
    workflow references are what let downstream analysis tell repeat workflows
    apart; leaving every submission on ``"default"`` hides that signal.
    """
    typer.echo(
        "Deprecated: `telemetry submit-session` is renamed to `driftshield submit`. "
        "Please use `driftshield submit`.",
        err=True,
    )
    run_submit(
        path=path,
        source_session_id=source_session_id,
        workflow_reference=workflow_reference,
        project_reference=project_reference,
        source_report_id=source_report_id,
        agent_id=agent_id,
        model_name=model_name,
        model_version=model_version,
        dry_run_redaction=dry_run_redaction,
        show_manifest=show_manifest,
        force_unknown_shape=force_unknown_shape,
        include_analysis=include_analysis,
        tier=tier,
        environment=environment,
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
