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


ERROR_AT_END = FIXTURES_DIR / "sample_claude_code_tool_error_at_end.jsonl"
RECOVERED = FIXTURES_DIR / "sample_claude_code_tool_error_recovered.jsonl"
SUCCESS = FIXTURES_DIR / "sample_claude_code_tool_success.jsonl"
BREAK_POINT_SENTENCE = (
    "The run ended on event #2 (Bash), a tool call that reported an error and was never recovered."
)


@pytest.mark.parametrize("report_type", ["summary", "full"])
def test_report_error_at_session_end_names_the_final_failed_tool_call(report_type):
    result = runner.invoke(app, ["report", str(ERROR_AT_END), "--type", report_type])

    assert result.exit_code == 0
    assert "Visible break-point candidate: event #2 (Bash)." in result.stdout
    assert BREAK_POINT_SENTENCE in result.stdout
    assert "found 0 risk-flagged events" in result.stdout


def test_report_full_cites_the_tool_error_evidence():
    result = runner.invoke(app, ["report", str(ERROR_AT_END)])

    assert result.exit_code == 0
    assert "Risk State Transition Mapping" in result.stdout
    assert "failure_context.signal:tool_marked_error" in result.stdout


def test_report_json_error_at_session_end_break_point():
    result = runner.invoke(app, ["report", str(ERROR_AT_END), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["candidate_break_point"]["status"] == "identified"
    assert data["candidate_break_point"]["strategy"] == "final_tool_error"
    assert data["summary"]["where_it_broke"] == "Visible break-point candidate: event #2 (Bash)."


@pytest.mark.parametrize("fixture", [RECOVERED, SUCCESS], ids=["recovered", "success"])
@pytest.mark.parametrize("report_type", ["summary", "full"])
def test_report_recovered_and_successful_runs_have_no_break_point(fixture, report_type):
    result = runner.invoke(app, ["report", str(fixture), "--type", report_type])

    assert result.exit_code == 0
    assert "No clear break point detected" in result.stdout
    assert BREAK_POINT_SENTENCE not in result.stdout
