from pathlib import Path

import pytest
import typer

from driftshield.cli.commands.evaluate_signatures import evaluate_signatures


def test_evaluate_signatures_writes_metrics(tmp_path: Path) -> None:
    dataset = Path(__file__).resolve().parents[2] / "data" / "signature-benchmark.jsonl"
    output = tmp_path / "signature-benchmark.json"

    evaluate_signatures(dataset=dataset, output=output, min_f1=0.9)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert '"dataset_size": 20' in content


def test_evaluate_signatures_fails_when_threshold_too_high(tmp_path: Path) -> None:
    dataset = Path(__file__).resolve().parents[2] / "data" / "signature-benchmark.jsonl"
    output = tmp_path / "signature-benchmark.json"

    with pytest.raises(typer.Exit) as exc_info:
        evaluate_signatures(dataset=dataset, output=output, min_f1=1.1)

    assert exc_info.value.exit_code == 1
