from datetime import datetime, timezone
import json
import uuid

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.db.engine import get_engine
from driftshield.db.models import AnalystValidationModel, Base, SessionModel


runner = CliRunner()


def test_export_validations_command_writes_jsonl(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    engine = get_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        session_id = uuid.uuid4()
        db.add(
            SessionModel(
                id=session_id,
                started_at=datetime.now(timezone.utc),
                status="completed",
                agent_id="agent",
                source_session_id="dogfood-session-123",
                source_path="fixtures/dogfood/session.jsonl",
                parser_version="openclaw@1",
            )
        )
        db.add(
            AnalystValidationModel(
                session_id=session_id,
                target_type="risk_flag",
                target_ref="abc123:coverage_gap",
                verdict="accept",
                confidence=0.9,
                reviewer="demo",
                notes="ok",
                metadata_json={
                    "node_id": "abc123",
                    "flag_name": "coverage_gap",
                    "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
                },
                shareable=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    output = tmp_path / "out.jsonl"
    result = runner.invoke(app, ["export-validations", "--output", str(output)])

    assert result.exit_code == 0
    assert "Exported 1 validation record" in result.output
    assert output.exists()
    payload = json.loads(output.read_text().strip())
    assert payload["review_outcome"]["label"] == "useful_failure"
    assert payload["session_provenance"]["source_session_id"] == "dogfood-session-123"
