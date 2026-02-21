import json

from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


def test_evaluate_classifier_command_outputs_metrics(tmp_path):
    rows = [
        {
            "title": "Agent ignored tool error",
            "text": "agent tool error hallucinated wrong output",
            "label": "agentic_failure",
        },
        {
            "title": "Build failure",
            "text": "pip install import error",
            "label": "non_agentic_bug",
        },
    ]

    dataset = tmp_path / "gold.jsonl"
    with dataset.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    result = runner.invoke(
        app,
        ["evaluate-classifier", "--dataset", str(dataset)],
    )

    assert result.exit_code == 0
    assert "Precision:" in result.output
    assert "Recall:" in result.output
    assert "F1:" in result.output
