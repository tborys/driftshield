"""Top-level submit command for uploading finished sessions to DriftShield."""

from __future__ import annotations

from pathlib import Path

import typer

from driftshield.cli._submit import run_submit


def submit(
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
            "Declared run environment: production, staging, test, or demo. "
            "Both lanes declare production by default; pass this only for the "
            "uncommon non-production contribution."
        ),
    ),
) -> None:
    """Upload a finished session to DriftShield for hosted failure investigation.

    The client redacts the transcript locally before upload. Use --tier teams
    (with DRIFTSHIELD_API_KEY) for the authenticated hosted Teams lane, or the
    default --tier oss for the unauthenticated community lane. Pass
    --include-analysis to attach the local matcher verdict so the hosted
    investigation matches what you get locally."""

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

