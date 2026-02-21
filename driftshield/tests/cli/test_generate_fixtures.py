from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


def test_generate_fixtures_command_writes_files(tmp_path):
    out_dir = tmp_path / "fixtures"

    result = runner.invoke(
        app,
        ["generate-fixtures", "--output-dir", str(out_dir), "--include-clean"],
    )

    assert result.exit_code == 0
    assert "Generated" in result.output
    assert (out_dir / "coverage_gap.jsonl").exists()
    assert (out_dir / "assumption_introduction.jsonl").exists()
    assert (out_dir / "cross_tool_contamination.jsonl").exists()
    assert (out_dir / "clean_session.jsonl").exists()
