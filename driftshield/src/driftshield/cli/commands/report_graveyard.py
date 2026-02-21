from pathlib import Path

import typer

from driftshield.graveyard.reporting import build_report, to_markdown


def report_graveyard(
    input_path: Path = typer.Option(
        Path("data/graveyard/candidates.jsonl"), "--input", "-i"
    ),
    output: Path = typer.Option(
        Path("data/graveyard/report.md"), "--output", "-o"
    ),
) -> None:
    """Generate markdown summary report from graveyard candidate JSONL."""
    report = build_report(input_path)
    markdown = to_markdown(report)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")

    typer.echo(f"Total candidates: {report.total_candidates}")
    typer.echo(f"Output: {output}")
