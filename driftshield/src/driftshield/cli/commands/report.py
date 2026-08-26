"""Report command for DriftShield CLI."""

import json
from pathlib import Path

import typer

from driftshield.public import analyse_run
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.json_export import export_json
from driftshield.reports.markdown import render_markdown
from driftshield.reports.models import ReportType


def report_command(
    path: Path = typer.Argument(..., help="Path to transcript file"),
    report_type: str = typer.Option("full", "--type", help="Report type: full or summary"),
    output_format: str = typer.Option(
        "markdown",
        "--format",
        "-f",
        help="Output format: markdown or json",
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    parser_name: str | None = typer.Option(None, "--parser", help="Parser to use"),
):
    """Generate a forensic analysis report from a transcript."""
    if not path.exists():
        typer.echo(f"Error: {path} not found", err=True)
        raise typer.Exit(1)

    try:
        run = analyse_run(path.read_bytes(), source=str(path), format=parser_name)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    session, result = run.session, run.analysis

    # Build and render report
    rt = ReportType(report_type)
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=rt)
    if output_format == "markdown":
        rendered = render_markdown(report_data)
    elif output_format == "json":
        rendered = json.dumps(export_json(report_data), indent=2) + "\n"
    else:
        typer.echo(f"Error: unsupported output format {output_format!r}", err=True)
        raise typer.Exit(1)

    if output:
        output.write_text(rendered)
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(rendered)
