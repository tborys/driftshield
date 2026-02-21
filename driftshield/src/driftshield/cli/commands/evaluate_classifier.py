import json
from pathlib import Path

import typer

from driftshield.graveyard.evaluation import evaluate_dataset


def evaluate_classifier(
    dataset: Path = typer.Option(..., "--dataset", help="Gold-labeled JSONL dataset path"),
    threshold: int = typer.Option(4, "--threshold", help="Positive classification threshold"),
) -> None:
    """Evaluate graveyard classifier quality against a gold-labeled dataset."""
    rows: list[dict] = []
    with dataset.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    result = evaluate_dataset(rows, positive_threshold=threshold)

    typer.echo(f"Total: {result.total}")
    typer.echo(f"Precision: {result.precision:.3f}")
    typer.echo(f"Recall: {result.recall:.3f}")
    typer.echo(f"F1: {result.f1:.3f}")
    typer.echo(
        "Confusion: "
        f"TP={result.true_positive}, FP={result.false_positive}, "
        f"TN={result.true_negative}, FN={result.false_negative}"
    )
