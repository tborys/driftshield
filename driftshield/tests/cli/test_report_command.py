import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


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
    filepath.write_text("\n".join(json.dumps(l) for l in lines))
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
