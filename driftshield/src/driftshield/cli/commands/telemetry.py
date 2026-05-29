"""CLI commands for consent-gated Phase 2a telemetry."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console

from driftshield.intake_contract import (
    DEFAULT_WORKFLOW_REFERENCE,
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    RedactionManifest,
)
from driftshield.recursive_redactor import (
    REDACTION_RULESET_VERSION,
    REDACTOR_VERSION,
)
from driftshield.cli._session_payload import load_session_payload
from driftshield.cli._signature_summary import build_signature_summary_from_session
from driftshield.remote_submission import (
    OssRemoteSubmissionConfig,
    RemoteSubmissionError,
    UnknownTranscriptShapeError,
    build_oss_submission_request,
    build_redacted_payload,
    detect_shape,
    post_oss_submission,
    redact_payload_with_manifest,
)
from driftshield.remote_upload import (
    INLINE_PAYLOAD_THRESHOLD_BYTES,
    OssUploadConfig,
    TeamsUploadConfig,
    submit_oss_via_presigned_upload,
    submit_teams_via_presigned_upload,
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
        payload = load_session_payload(path)
    except OSError as exc:
        console.print(f"[red]Error:[/red] Could not read session file: {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}.")
        raise typer.Exit(1) from exc

    if dry_run_redaction or show_manifest:
        redaction_result = redact_payload_with_manifest(payload)
        shape = detect_shape(payload) or "unknown"
        if dry_run_redaction:
            entries = [
                {
                    "path": entry.path,
                    "category": entry.category,
                    "sample_hash": entry.sample_hash,
                }
                for entry in redaction_result.entries
            ]
            typer.echo(
                json.dumps(
                    {"detected_shape": shape, "entries": entries},
                    indent=2,
                )
            )
        if show_manifest:
            manifest = RedactionManifest(
                manifest_version=REDACTION_MANIFEST_VERSION,
                redaction_applied=True,
                redacted_fields=sorted(REQUIRED_REDACTION_FIELDS),
                redactor_version=REDACTOR_VERSION,
                redaction_ruleset_version=REDACTION_RULESET_VERSION,
            )
            manifest_payload = manifest.model_dump(mode="json")
            manifest_payload["detected_shape"] = shape
            manifest_payload["ruleset_entry_count"] = len(redaction_result.entries)
            typer.echo(json.dumps(manifest_payload, indent=2))
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

    summary = None
    if include_analysis:
        try:
            summary = build_signature_summary_from_session(path)
        except Exception as exc:  # noqa: BLE001
            typer.echo(
                "error: --include-analysis specified but "
                f"build_signature_summary_from_session(...) failed: {exc}",
                err=True,
            )
            raise typer.Exit(code=2) from exc
        if summary is None:
            typer.echo(
                "error: --include-analysis specified but "
                "build_signature_summary_from_session(...) could not produce "
                "a summary (no parser detected or session yielded no events). "
                "Re-run without --include-analysis or supply a parseable session.",
                err=True,
            )
            raise typer.Exit(code=2)

    resolved_tier = tier.strip().lower()
    if resolved_tier not in {"oss", "teams"}:
        console.print("[red]Error:[/red] --tier must be 'oss' or 'teams'.")
        raise typer.Exit(1)

    teams_api_key: str | None = None
    if resolved_tier == "teams":
        teams_api_key = os.environ.get("DRIFTSHIELD_API_KEY") or os.environ.get(
            "API_KEY"
        )
        if not teams_api_key:
            console.print(
                "[red]Error:[/red] --tier teams requires DRIFTSHIELD_API_KEY "
                "(or API_KEY) in the environment."
            )
            raise typer.Exit(1)

    # Redact once to measure the canonical size (uncapped) and decide the
    # lane. The size-capped SubmissionEnvelope model is only built on the
    # small inline OSS path; large transcripts exceed that cap by design
    # and take the presigned-S3 lane instead.
    try:
        redacted_payload = build_redacted_payload(
            payload=payload, force_unknown_shape=force_unknown_shape
        )
    except UnknownTranscriptShapeError as exc:
        console.print(
            f"[red]Error:[/red] {exc} "
            "Inspect the payload with --dry-run-redaction first."
        )
        raise typer.Exit(1) from exc

    payload_size = len(
        json.dumps(
            redacted_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    is_large = payload_size > INLINE_PAYLOAD_THRESHOLD_BYTES

    try:
        if resolved_tier == "teams":
            assert teams_api_key is not None
            result = submit_teams_via_presigned_upload(
                config=TeamsUploadConfig(
                    intake_url=config.remote_intake_url, api_key=teams_api_key
                ),
                payload=redacted_payload,
                workflow_reference=resolved_workflow_reference,
                file_name=path.name,
            )
        elif is_large:
            result = submit_oss_via_presigned_upload(
                config=OssUploadConfig(intake_url=config.remote_intake_url),
                payload=redacted_payload,
                workflow_reference=resolved_workflow_reference,
                file_name=path.name,
            )
        else:
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
                    signature_summary=summary,
                )
            except UnknownTranscriptShapeError as exc:
                console.print(
                    f"[red]Error:[/red] {exc} "
                    "Inspect the payload with --dry-run-redaction first."
                )
                raise typer.Exit(1) from exc
            submission_config = OssRemoteSubmissionConfig(
                intake_url=config.remote_intake_url
            )
            result = post_oss_submission(
                config=submission_config, submission=submission
            )
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
            f"{SUPPORTED_CONTRACT_VERSION}. The server is in its post-bump "
            "deprecation window: submissions are still accepted, but the "
            "server operator should upgrade before the window closes."
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
