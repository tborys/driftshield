"""Report command for DriftShield CLI."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import typer

from driftshield.cli.parsers import detect_parser, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
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

    # Detect and run parser
    name = parser_name or detect_parser(path)
    if name is None:
        typer.echo(f"Error: could not detect parser for {path.name}", err=True)
        raise typer.Exit(1)

    parser = get_parser(name)
    events = parser.parse_file(str(path))

    if not events:
        typer.echo("No events found in transcript", err=True)
        raise typer.Exit(1)

    # Analyse
    result = analyze_session(events)
    session = DomainSession(
        id=events[0].session_id or uuid.uuid4(),
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp or datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )

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
