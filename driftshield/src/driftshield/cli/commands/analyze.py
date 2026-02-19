"""Analyze command for DriftShield CLI."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser, ParserNotFoundError
from driftshield.cli.output import format_summary, format_json, format_verbose_table, format_quiet
from driftshield.cli.discovery import discover_sessions, resolve_session
from driftshield.core.analysis.session import analyze_session


console = Console()


def analyze(
    path: Optional[str] = typer.Argument(
        None,
        help="Session file, directory, or session ID to analyze.",
    ),
    project: bool = typer.Option(
        False,
        "--project",
        help="Analyze sessions for current project.",
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
    fail_on: Optional[str] = typer.Option(
        None,
        "--fail-on",
        help="Exit 1 if specified risks detected (comma-separated).",
    ),
    fail_threshold: Optional[int] = typer.Option(
        None,
        "--fail-threshold",
        help="Exit 1 if N or more events flagged.",
    ),
) -> None:
    """Analyse session(s) for reasoning risks."""
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    # Collect files to analyze
    files_to_analyze: list[Path] = []

    if project:
        sessions = discover_sessions(Path.cwd(), claude_base)
        if not sessions:
            console.print("No sessions found for this project.")
            raise typer.Exit(0)
        files_to_analyze = [s.path for s in sessions]
    elif path is not None:
        resolved = resolve_session(path, Path.cwd(), claude_base)
        if resolved is None:
            direct = Path(path).expanduser().resolve()
            if direct.exists():
                resolved = direct
            else:
                console.print(f"[red]Error:[/red] Could not find session: {path}")
                raise typer.Exit(1)
        files_to_analyze = [resolved]
    else:
        console.print("[red]Error:[/red] No path provided. Use --project or specify a file path.")
        raise typer.Exit(1)

    # Analyze each file
    all_results = []
    for file_path in files_to_analyze:
        effective_parser = parser
        if effective_parser == "auto":
            detected = detect_parser(file_path)
            if detected is None:
                console.print(
                    f"[yellow]Warning:[/yellow] Could not detect parser for '{file_path.name}', skipping"
                )
                continue
            effective_parser = detected

        try:
            parser_instance = get_parser(effective_parser)
        except ParserNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

        try:
            events = parser_instance.parse_file(str(file_path))
            result = analyze_session(events)
            all_results.append((file_path, result))
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to analyze {file_path.name}: {e}")
            if len(files_to_analyze) == 1:
                raise typer.Exit(1)
            continue

    if not all_results:
        console.print("No sessions analyzed.")
        raise typer.Exit(1)

    # Check CI failure conditions
    should_fail = False
    fail_reasons: list[str] = []

    for file_path, result in all_results:
        if fail_on:
            risk_types = [r.strip() for r in fail_on.split(",")]
            for risk_type in risk_types:
                if result.risk_summary.get(risk_type, 0) > 0:
                    should_fail = True
                    fail_reasons.append(f"{risk_type} detected in {file_path.stem}")

        if fail_threshold is not None:
            if result.flagged_events >= fail_threshold:
                should_fail = True
                fail_reasons.append(
                    f"{result.flagged_events} flagged events in {file_path.stem} "
                    f"(threshold: {fail_threshold})"
                )

    # Output results
    if json_output:
        import json
        if len(all_results) == 1:
            console.print(format_json(all_results[0][1]))
        else:
            data = []
            for file_path, result in all_results:
                import json as json_lib
                data.append(json_lib.loads(format_json(result)))
            console.print(json.dumps(data, indent=2))
    elif quiet:
        for file_path, result in all_results:
            if len(all_results) > 1:
                console.print(f"[bold]{file_path.stem}:[/bold] ", end="")
            console.print(format_quiet(result))
    else:
        for i, (file_path, result) in enumerate(all_results):
            if i > 0:
                console.print()
                console.print("\u2500" * 40)
                console.print()

            if len(all_results) > 1:
                console.print(f"[bold]Session: {file_path.stem}[/bold]")
                console.print()

            console.print(format_summary(result))

            if verbose:
                console.print()
                console.print(format_verbose_table(result))

    # Exit with failure if CI conditions met
    if should_fail:
        if not quiet:
            console.print()
            console.print("[red]FAIL:[/red]")
            for reason in fail_reasons:
                console.print(f"  - {reason}")
        raise typer.Exit(1)
