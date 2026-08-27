"""The ``driftshield submit`` skin over ``analyse_run`` + ``submit``."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.public import (
    NoParseableEventsError,
    SubmitError,
    analyse_run,
    submit,
    workspace_key_from_environment,
)

console = Console(force_terminal=True)


def resolve_workspace_key(tier: str) -> str | None:
    """The API key the workspace lane needs, or ``None`` on the community lane."""
    if tier.strip().lower() not in {"teams", "workspace"}:
        return None
    key = workspace_key_from_environment()
    if not key:
        raise SubmitError(
            "--tier teams requires DRIFTSHIELD_API_KEY (or API_KEY) in the environment."
        )
    return key


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
    include_analysis: bool,
    tier: str,
    environment: str | None,
) -> None:
    """Analyse one session file and submit its redacted transcript once."""
    try:
        run = analyse_run(path.read_bytes(), source=str(path))
    except OSError as exc:
        console.print(f"[red]Error:[/red] Could not read session file: {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        console.print(
            f"[red]Error:[/red] {exc}. Inspect the file with `driftshield analyze` first."
        )
        raise typer.Exit(1) from exc

    if dry_run_redaction or show_manifest:
        manifest = dict(run.redaction_manifest)
        entries = manifest.pop("entries")
        if dry_run_redaction:
            typer.echo(
                json.dumps({"detected_shape": run.detected_format, "entries": entries}, indent=2)
            )
        if show_manifest:
            manifest["detected_shape"] = run.detected_format
            manifest["ruleset_entry_count"] = len(entries)
            typer.echo(json.dumps(manifest, indent=2))
        return

    try:
        receipt = submit(
            run,
            tier,
            resolve_workspace_key(tier),
            source_session_id=source_session_id,
            workflow_reference=workflow_reference,
            project_reference=project_reference,
            source_report_id=source_report_id,
            agent_id=agent_id,
            model_name=model_name,
            model_version=model_version,
            environment=environment,
            include_analysis=include_analysis,
        )
    except SubmitError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if receipt.deprecation_warning:
        console.print(f"[yellow]Deprecation:[/yellow] {receipt.deprecation_warning}")
    console.print(
        f"Submitted. submission_id={receipt.submission_id} status={receipt.processing_status}"
    )


__all__ = ["NoParseableEventsError", "resolve_workspace_key", "run_submit"]
