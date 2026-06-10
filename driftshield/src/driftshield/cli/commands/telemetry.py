"""CLI commands for consent-gated telemetry."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console

from driftshield.core.canonical_analysis import DECLARED_ENVIRONMENTS
from driftshield.core.models import EnvironmentClass
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
    derive_openclaw_provenance,
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

    resolved_tier = tier.strip().lower()
    if resolved_tier not in {"oss", "teams"}:
        console.print("[red]Error:[/red] --tier must be 'oss' or 'teams'.")
        raise typer.Exit(1)

    resolved_environment: str | None = None
    if environment is not None:
        resolved_environment = environment.strip().lower()
        if resolved_environment not in DECLARED_ENVIRONMENTS:
            valid = ", ".join(sorted(DECLARED_ENVIRONMENTS))
            console.print(
                f"[red]Error:[/red] --environment must be one of: {valid}."
            )
            raise typer.Exit(1)
        if resolved_tier != "oss":
            console.print(
                "[red]Error:[/red] --environment applies to the community "
                "(oss) lane only."
            )
            raise typer.Exit(1)

    config = TelemetryService().load_config()
    if resolved_tier == "oss":
        intake_url = effective_oss_intake_url(config)
        if intake_url is None:
            console.print(
                "[red]Error:[/red] Remote submission is disabled "
                "(`telemetry remote-disable`). Run `driftshield telemetry "
                "remote-enable --intake-url URL` to re-enable."
            )
            raise typer.Exit(1)
    else:
        intake_url = config.remote_intake_url
        if intake_url is None:
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

    # Real provenance for OpenClaw trajectories: the harness/agent and the
    # driving provider/model come from the trajectory itself when the caller
    # did not pass explicit values. Explicit flags always win.
    derived_provenance = derive_openclaw_provenance(payload)
    if agent_id is None:
        agent_id = derived_provenance.get("agent_id")
    if model_name is None:
        model_name = derived_provenance.get("model_name")

    # Community opt-in is the production declaration: stamp the declared
    # environment before redaction so it rides both the inline and the
    # presigned lanes. An environment already declared in the session JSON
    # is kept; --environment wins over everything.
    if resolved_tier == "oss":
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            # The envelope contract expects a metadata mapping; a malformed
            # value cannot carry the declared environment.
            metadata = {}
            payload["metadata"] = metadata
        if resolved_environment is not None:
            metadata["environment"] = resolved_environment
        else:
            metadata.setdefault("environment", EnvironmentClass.PRODUCTION.value)

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

    # The provenance surface the inline lane carries on the envelope must
    # also ride the presigned lane (else large + Teams submissions lose it).
    provenance: dict[str, object] = {
        "source_session_id": source_session_id or path.stem,
    }
    for key, value in (
        ("project_reference", project_reference),
        ("source_report_id", source_report_id),
        ("agent_id", agent_id),
        ("model_name", model_name),
        ("model_version", model_version),
    ):
        if value is not None:
            provenance[key] = value
    if summary is not None:
        provenance["signature_summary"] = summary.model_dump(mode="json")

    try:
        if resolved_tier == "teams":
            assert teams_api_key is not None
            result = submit_teams_via_presigned_upload(
                config=TeamsUploadConfig(
                    intake_url=intake_url, api_key=teams_api_key
                ),
                payload=redacted_payload,
                workflow_reference=resolved_workflow_reference,
                file_name=path.name,
                provenance=provenance,
            )
        elif is_large:
            result = submit_oss_via_presigned_upload(
                config=OssUploadConfig(intake_url=intake_url),
                payload=redacted_payload,
                workflow_reference=resolved_workflow_reference,
                file_name=path.name,
                provenance=provenance,
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
            submission_config = OssRemoteSubmissionConfig(intake_url=intake_url)
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
