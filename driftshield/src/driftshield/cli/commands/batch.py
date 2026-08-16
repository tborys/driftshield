"""Batch command: analyse (and optionally submit) a directory or archive of transcripts."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from driftshield.cli._batch import BatchReport, run_batch

console = Console(force_terminal=True)


def batch(
    source: Path = typer.Argument(
        ...,
        help="Directory of transcripts, or a .zip/.tar.gz/.tgz archive of transcripts.",
    ),
    submit: bool = typer.Option(
        False,
        "--submit",
        help=(
            "Submit every successfully analysed file through the same lane as "
            "'driftshield submit'. Off by default -- with no --submit, batch "
            "makes no network call at all."
        ),
    ),
    tier: str = typer.Option(
        "oss",
        "--tier",
        help=(
            "Submission tier when --submit is passed: 'oss' (unauthenticated "
            "community lane) or 'teams' (authenticated; requires "
            "DRIFTSHIELD_API_KEY). Ignored when --submit is not passed."
        ),
    ),
    include_analysis: bool = typer.Option(
        False,
        "--include-analysis",
        help=(
            "When submitting, attach the local matcher's signature_summary to "
            "each envelope (same as 'driftshield submit --include-analysis'). "
            "Ignored when --submit is not passed."
        ),
    ),
    workflow_reference: str | None = typer.Option(
        None,
        "--workflow-reference",
        help=(
            "Workflow identifier stamped on every submitted envelope, "
            "matching 'driftshield submit --workflow-reference' in name and "
            "meaning. When omitted, batch derives one per file from its "
            "immediate parent directory (stable, sanitised) instead of "
            "falling back to the module default -- so a tree of "
            "per-project session directories yields one workflow reference "
            "per project. Resolution order: explicit flag, then "
            "derived-per-directory, then the module default. Ignored when "
            "--submit is not passed."
        ),
    ),
    backfill: bool = typer.Option(
        False,
        "--backfill",
        help=(
            "Declare every submitted envelope a post-hoc pilot import: sets "
            "top-level 'backfill: true' so the server indexes recurrence and "
            "lifecycle trends on original session timestamps instead of "
            "arrival time. Requires --submit and --tier teams (the "
            "authenticated lane) -- the unauthenticated community tier "
            "rejects it client-side before any upload. With --backfill but "
            "no --submit, this is a no-op with a warning."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output the batch report as JSON instead of a Rich-formatted summary.",
    ),
) -> None:
    """Analyse every transcript under a directory or archive without aborting on a bad file.

    ``source`` may be a directory (walked recursively) or a .zip/.tar.gz/.tgz
    archive (extracted to a cleaned-up temp directory). Each discovered file
    is auto-detected the same way 'driftshield analyze' does: a file with no
    matching parser is recorded 'skipped', and a file that raises during
    parsing or analysis is recorded 'failed' with the exception message as
    the reason -- neither aborts the rest of the batch.

    Submission is opt-in. Pass --submit to upload every successfully
    analysed file through the same redact-then-submit path as 'driftshield
    submit', recording 'submitted' (with the returned submission id) or
    'failed' per file. Without --submit, every file that analysed
    successfully is reported 'analysed-only' and nothing is ever uploaded.

    workflow_reference precedence for each submitted file: --workflow-reference
    flag (one value for the whole batch), then a value derived from the
    file's immediate parent directory, then the module default 'default'.
    This differs from 'driftshield submit', which falls back to a
    workflow_reference already present in the payload before the module
    default -- batch derives from the directory instead of consulting the
    payload. See docs/telemetry.md for the full comparison.

    Exits non-zero only if at least one file's outcome is 'failed'; a
    'skipped' file does not affect the exit code.
    """
    if not source.exists():
        console.print(f"[red]Error:[/red] '{source}' does not exist.")
        raise typer.Exit(1)

    if backfill and submit and tier.strip().lower() != "teams":
        console.print(
            "[red]Error:[/red] --backfill requires --tier teams (the "
            "authenticated lane); the community tier does not accept a "
            "backfill declaration."
        )
        raise typer.Exit(1)

    if backfill and not submit:
        console.print(
            "[yellow]Warning:[/yellow] --backfill has no effect without "
            "--submit; nothing will be uploaded."
        )

    if workflow_reference is not None and not submit:
        console.print(
            "[yellow]Warning:[/yellow] --workflow-reference has no effect "
            "without --submit; nothing will be uploaded."
        )

    try:
        report = run_batch(
            source,
            submit=submit,
            tier=tier,
            include_analysis=include_analysis,
            backfill=backfill,
            workflow_reference=workflow_reference,
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report)

    if report.has_failures:
        raise typer.Exit(1)


def _print_report(report: BatchReport) -> None:
    totals = report.totals
    console.print("[bold]DriftShield Batch Report[/bold]")
    console.print(
        f"submitted={totals['submitted']}  analysed-only={totals['analysed-only']}  "
        f"failed={totals['failed']}  skipped={totals['skipped']}"
    )

    if not report.files:
        console.print("No files discovered.")
        return

    console.print()
    table = Table()
    table.add_column("File")
    table.add_column("Outcome")
    table.add_column("Detail")
    for entry in report.files:
        detail = entry.submission_id or entry.reason or ""
        table.add_row(entry.path, entry.outcome, detail)
    console.print(table)
