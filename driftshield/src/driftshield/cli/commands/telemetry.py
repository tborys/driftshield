"""CLI commands for consent-gated Phase 2a telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.intake_contract import (
    DEFAULT_WORKFLOW_REFERENCE,
    SUPPORTED_CONTRACT_VERSION,
)
from driftshield.remote_submission import (
    OssRemoteSubmissionConfig,
    RemoteSubmissionError,
    UnknownTranscriptShapeError,
    build_oss_submission_request,
    detect_shape,
    post_oss_submission,
    redact_payload_with_manifest,
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
        "remote_enabled": config.remote_intake_url is not None,
        "remote_intake_url": config.remote_intake_url,
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
        None, "--agent-id", help="Optional agent identifier (phase3g.v1 provenance)."
    ),
    model_name: str | None = typer.Option(
        None, "--model-name", help="Optional model name (phase3g.v1 provenance)."
    ),
    model_version: str | None = typer.Option(
        None, "--model-version", help="Optional model version (phase3g.v1 provenance)."
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
) -> None:
    """Build a phase3g.v1 envelope from a finished session JSON and POST once to the OSS intake URL.

    The OSS lane is unauthenticated. No X-API-Key header is sent, no installation_id
    or consent_state is included in the request. The server binds the persisted row
    to the in-stack OSS fallback installation + consent.

    ``workflow_reference`` precedence: --workflow-reference flag, then
    session JSON's ``workflow_reference`` field, then ``"default"``. The
    Phase 3i recurrence matcher requires distinct workflow references to
    light up the Emerging signal; leaving every submission on ``"default"``
    masks recurrence.
    """
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

    if dry_run_redaction or show_manifest:
        result = redact_payload_with_manifest(payload)
        shape = detect_shape(payload) or "unknown"
        if dry_run_redaction:
            entries = [
                {
                    "path": entry.path,
                    "category": entry.category,
                    "sample_hash": entry.sample_hash,
                }
                for entry in result.entries
            ]
            typer.echo(
                json.dumps(
                    {"detected_shape": shape, "entries": entries},
                    indent=2,
                )
            )
        if show_manifest:
            typer.echo(
                json.dumps(
                    {
                        "manifest_version": "redaction-manifest.v1",
                        "redaction_applied": True,
                        "redacted_fields": sorted(["prompts", "responses", "user_identifiers"]),
                        "detected_shape": shape,
                        "ruleset_entry_count": len(result.entries),
                    },
                    indent=2,
                )
            )
        return

    config = TelemetryService().load_config()
    if not config.remote_intake_url:
        console.print(
            "[red]Error:[/red] Remote submission is not configured. "
            "Run `driftshield telemetry remote-enable --intake-url URL` first."
        )
        raise typer.Exit(1)

    resolved_workflow_reference = workflow_reference
    if resolved_workflow_reference is None:
        payload_workflow = payload.get("workflow_reference")
        if isinstance(payload_workflow, str) and payload_workflow.strip():
            resolved_workflow_reference = payload_workflow
    if resolved_workflow_reference is None:
        resolved_workflow_reference = DEFAULT_WORKFLOW_REFERENCE

    try:
        submission = build_oss_submission_request(
            source_session_id=source_session_id or path.stem,
            payload=payload,
            workflow_reference=resolved_workflow_reference,
            project_reference=project_reference,
            source_report_id=source_report_id,
            force_unknown_shape=force_unknown_shape,
            agent_id=agent_id,
            model_name=model_name,
            model_version=model_version,
        )
    except UnknownTranscriptShapeError as exc:
        console.print(
            f"[red]Error:[/red] {exc} "
            "Inspect the payload with --dry-run-redaction first."
        )
        raise typer.Exit(1) from exc

    submission_config = OssRemoteSubmissionConfig(intake_url=config.remote_intake_url)
    try:
        result = post_oss_submission(config=submission_config, submission=submission)
    except RemoteSubmissionError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if (
        result.server_contract_version is not None
        and result.server_contract_version != SUPPORTED_CONTRACT_VERSION
    ):
        console.print(
            f"[yellow]Deprecation:[/yellow] intake server advertises "
            f"{result.server_contract_version}; this client is on "
            f"{SUPPORTED_CONTRACT_VERSION}. Coordinate the server upgrade "
            "before the 90-day sunset documented at "
            "driftshield-meta/docs/operations/phase-3i-envelope-deprecation.md."
        )

    response = result.response
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
