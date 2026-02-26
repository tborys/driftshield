import json
from pathlib import Path

import typer

from driftshield.core.signatures.benchmark import (
    evaluate_signature_library,
    load_benchmark_dataset,
)


def evaluate_signatures(
    dataset: Path = typer.Option(
        Path("data/signature-benchmark.jsonl"),
        "--dataset",
        help="JSONL benchmark fixture file for signature-family evaluation.",
    ),
    output: Path = typer.Option(
        Path("metrics/signature-benchmark.json"),
        "--output",
        help="Write benchmark summary JSON to this path.",
    ),
    min_f1: float = typer.Option(
        0.75,
        "--min-f1",
        help="Fail command when any risk-family F1 is below this threshold.",
    ),
) -> None:
    """Evaluate signature-library benchmark quality and emit JSON metrics."""
    rows = load_benchmark_dataset(dataset)
    result = evaluate_signature_library(rows)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    typer.echo(f"Dataset size: {result.dataset_size}")
    typer.echo(f"Exact match rate: {result.exact_match_rate:.3f}")
    typer.echo(f"Average candidate signatures: {result.average_candidate_signatures:.3f}")
    typer.echo(f"Wrote: {output}")

    below_threshold = []
    for risk_class, metrics in result.per_family.items():
        typer.echo(
            f"{risk_class.value}: precision={metrics.precision:.3f}, "
            f"recall={metrics.recall:.3f}, f1={metrics.f1:.3f}"
        )
        if metrics.f1 < min_f1:
            below_threshold.append((risk_class.value, metrics.f1))

    if below_threshold:
        joined = ", ".join(f"{name}={score:.3f}" for name, score in below_threshold)
        typer.echo(f"Quality gate failed (min_f1={min_f1}): {joined}")
        raise typer.Exit(code=1)
