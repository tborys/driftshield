"""Analyze command for DriftShield CLI."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser, ParserNotFoundError
from driftshield.cli.output import format_summary, format_json, format_verbose_table, format_quiet
from driftshield.core.analysis.session import analyze_session


console = Console()


def analyze(
    path: Optional[Path] = typer.Argument(
        None,
        help="Session file or directory to analyze.",
        exists=False,
    ),
    parser: str = typer.Option(
        "auto",
        "--parser",
        "-p",
        help="Parser to use (auto, claude_code).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show full event table.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Minimal output.",
    ),
) -> None:
    """Analyse session(s) for reasoning risks."""
    if path is None:
        console.print("[red]Error:[/red] No path provided. Use --project or specify a file path.")
        raise typer.Exit(1)

    path = Path(path).expanduser().resolve()

    if not path.exists():
        console.print(f"[red]Error:[/red] Path not found: {path}")
        raise typer.Exit(1)

    # Determine parser
    if parser == "auto":
        detected = detect_parser(path)
        if detected is None:
            console.print(
                f"[red]Error:[/red] Could not detect parser for '{path.name}'\n"
                "Hint: Use --parser to specify format (available: claude_code)"
            )
            raise typer.Exit(1)
        parser = detected

    try:
        parser_instance = get_parser(parser)
    except ParserNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Parse and analyze
    try:
        if path.is_file():
            events = parser_instance.parse_file(str(path))
        else:
            console.print("[red]Error:[/red] Directory analysis not yet supported. Specify a file.")
            raise typer.Exit(1)

        result = analyze_session(events)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to analyze: {e}")
        raise typer.Exit(1)

    # Output
    if json_output:
        console.print(format_json(result))
    elif quiet:
        console.print(format_quiet(result))
    elif verbose:
        console.print(format_summary(result))
        console.print()
        console.print(format_verbose_table(result))
    else:
        console.print(format_summary(result))
