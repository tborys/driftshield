from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

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
    assert "signatures" in result.output


def test_installed_console_script_starts_without_test_module_imports(tmp_path):
    cli_path = Path(sys.executable).with_name("driftshield")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [str(cli_path), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "DriftShield - AI Decision Forensics CLI" in result.stdout


def test_python_module_entrypoint_exposes_cli(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")

    result = subprocess.run(
        [sys.executable, "-m", "driftshield.cli.main", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "DriftShield - AI Decision Forensics CLI" in result.stdout
