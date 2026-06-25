from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from driftshield.cli.main import app

runner = CliRunner()


def _write_session(tmp_path: Path) -> Path:
    # Minimal OpenClaw-shaped session the redactor recognises.
    session = {
        "events": [
            {"type": "session", "session_id": "s1"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        ],
        "metadata": {},
    }
    p = tmp_path / "session.json"
    p.write_text(json.dumps(session))
    return p


def test_run_submit_importable_and_callable():
    from driftshield.cli._submit import run_submit
    assert callable(run_submit)
