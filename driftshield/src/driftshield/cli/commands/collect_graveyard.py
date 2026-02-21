import json
from pathlib import Path

import typer

from driftshield.graveyard.collector import GraveyardCollector
from driftshield.graveyard.github_client import GhCliClient


def collect_graveyard(
    repo: list[str] = typer.Option(
        ..., "--repo", help="GitHub repo slug (repeatable, e.g. langchain-ai/langchain)"
    ),
    limit_per_repo: int = typer.Option(100, "--limit-per-repo"),
    output: Path = typer.Option(
        Path("data/graveyard/candidates.jsonl"), "--output", "-o"
    ),
) -> None:
    """Collect likely agentic failure threads from GitHub issues/comments."""
    client = GhCliClient()
    collector = GraveyardCollector(client)
    result = collector.collect(repos=repo, limit_per_repo=limit_per_repo)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for item in result.candidates:
            f.write(
                json.dumps(
                    {
                        "repo": item.repo,
                        "issue_number": item.issue_number,
                        "issue_url": item.issue_url,
                        "title": item.title,
                        "score": item.score,
                        "likelihood": item.likelihood,
                        "signals": item.signals,
                        "evidence_text": item.evidence_text,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    typer.echo(f"Repos scanned: {len(repo)}")
    typer.echo(f"Issues scanned: {result.total_issues}")
    typer.echo(f"Candidates: {result.candidate_count}")
    typer.echo(f"Output: {output}")
