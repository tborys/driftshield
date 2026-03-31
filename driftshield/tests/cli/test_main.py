from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


def test_cli_help_omits_private_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "collect-graveyard" not in result.output
    assert "report-graveyard" not in result.output
    assert "evaluate-classifier" not in result.output
    assert "evaluate-signatures" not in result.output
    assert "analyze" in result.output
    assert "report" in result.output
