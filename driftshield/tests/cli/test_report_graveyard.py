import json

from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


def test_report_graveyard_generates_markdown(tmp_path):
    input_path = tmp_path / "candidates.jsonl"
    rows = [
        {
            "repo": "langchain-ai/langchain",
            "issue_number": 1,
            "likelihood": "high",
            "signals": ["agentic_failure", "tool_call"],
        },
        {
            "repo": "microsoft/autogen",
            "issue_number": 2,
            "likelihood": "medium",
            "signals": ["agentic_failure"],
        },
    ]
    with input_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    output = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["report-graveyard", "--input", str(input_path), "--output", str(output)],
    )

    assert result.exit_code == 0
    assert "Total candidates: 2" in result.output
    markdown = output.read_text()
    assert "State of OSS Agent Failures" in markdown
    assert "langchain-ai/langchain" in markdown
