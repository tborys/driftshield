"""Shared upload implementation for the submit command surface."""

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
)

console = Console(force_terminal=True)


def run_submit(
    *,
    path: Path,
    source_session_id: str | None,
    workflow_reference: str | None,
    project_reference: str | None,
    source_report_id: str | None,
    agent_id: str | None,
    model_name: str | None,
    model_version: str | None,
    dry_run_redaction: bool,
    show_manifest: bool,
    force_unknown_shape: bool,
    include_analysis: bool,
    tier: str,
    environment: str | None,
) -> None:
    """Build a phase3g.v1 envelope from a finished session JSON and POST once to the configured intake URL (OSS community lane or authenticated Teams lane)."""

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

    # Submitting is the production declaration on both lanes: stamp the declared
    # environment before redaction so it rides both the inline and the presigned
    # lanes. An environment already declared in the session JSON is kept;
    # --environment wins over everything. Both tiers default to production (an
    # explicit non-production contribution is the uncommon case), so the hosted
    # investigation always lands a declared environment rather than an
    # undeclared run.
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
