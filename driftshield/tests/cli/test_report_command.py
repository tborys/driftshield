import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


@pytest.fixture
def sample_transcript(tmp_path):
    """Create a minimal JSONL transcript file."""
    from datetime import datetime, timezone
    lines = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/test"}}
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "contents"}
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    ]
    filepath = tmp_path / "transcript.jsonl"
    filepath.write_text("\n".join(json.dumps(line) for line in lines))
    return filepath


def test_report_command_outputs_markdown(sample_transcript):
    result = runner.invoke(app, ["report", str(sample_transcript)])
    assert result.exit_code == 0
    assert "Forensic Analysis Report" in result.stdout


def test_report_command_summary_type(sample_transcript):
    result = runner.invoke(app, ["report", str(sample_transcript), "--type", "summary"])
    assert result.exit_code == 0
    assert "Forensic Analysis Report" in result.stdout
    assert "Risk State Transition Mapping" not in result.stdout


def test_report_command_outputs_json(sample_transcript):
    result = runner.invoke(app, ["report", str(sample_transcript), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema_version"] == "forensic_report.v1"
    assert data["summary"]["what_happened"]
    assert data["evidence_index"]


def test_report_command_supports_bundled_quickstart_fixture(tmp_path):
    output = tmp_path / "quickstart-report.md"

    result = runner.invoke(
        app,
        [
            "report",
            str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
            "--type",
            "summary",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert "Forensic Analysis Report" in output.read_text()
