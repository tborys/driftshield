from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url


@pytest.fixture()
def migration_runner_module():
    module_path = Path(__file__).resolve().parents[2] / "migrations/lambda_handler.py"
    spec = spec_from_file_location("migration_runner", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_url_from_secret_percent_encodes_credentials(monkeypatch, migration_runner_module):
    class FakeSecretsClient:
        def get_secret_value(self, *, SecretId: str):
            assert SecretId == "arn:aws:secretsmanager:eu-west-1:123456789012:secret:test"
            return {
                "SecretString": (
                    '{"username":"runner","password":"p@ss:/?#[]!$&\'()*+,;=word",'
                    '"host":"db.example.internal","port":5432,"dbname":"driftshield"}'
                )
            }

    fake_boto3 = SimpleNamespace(client=lambda *args, **kwargs: FakeSecretsClient())
    monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)

    url = migration_runner_module._build_url_from_secret(
        "arn:aws:secretsmanager:eu-west-1:123456789012:secret:test"
    )

    assert "p@ss:/?#[]!$&'()*+,;=word" not in url
    parsed = make_url(url)
    assert parsed.username == "runner"
    assert parsed.password == "p@ss:/?#[]!$&'()*+,;=word"
    assert parsed.host == "db.example.internal"
    assert parsed.port == 5432
    assert parsed.database == "driftshield"


def test_redact_strips_raw_and_percent_encoded_passwords(migration_runner_module):
    database_url = "postgresql+psycopg2://runner:p%40ss%3Aword@db.example.internal:5432/driftshield"
    message = (
        "connect failed for postgresql+psycopg2://runner:p%40ss%3Aword@db.example.internal:5432/driftshield "
        "and raw password p@ss:word should not leak"
    )

    redacted = migration_runner_module._redact(message, database_url)

    assert "p%40ss%3Aword" not in redacted
    assert "p@ss:word" not in redacted
    assert "<redacted>" in redacted


def test_resolve_database_url_rejects_both_envs(monkeypatch, migration_runner_module):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://example")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:123:secret:test")

    with pytest.raises(migration_runner_module.MigrationRunnerError):
        migration_runner_module._resolve_database_url()


def test_verify_phase3h_handler_mode_bypasses_upgrade(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )
    monkeypatch.setattr(
        migration_runner_module,
        "_verify_phase3h_objects",
        lambda database_url: {
            "status": "ok",
            "mode": "verify_phase3h_objects",
            "head_revision": "20260511_03",
            "objects": [{"name": "tenants", "type": "BASE TABLE"}],
            "submissions_columns": [{"name": "tenant_id", "type": "uuid"}],
            "missing_objects": [],
            "missing_submission_columns": [],
        },
    )

    result = migration_runner_module.handler({"mode": "verify_phase3h_objects"}, None)

    assert result["status"] == "ok"
    assert result["mode"] == "verify_phase3h_objects"
    assert result["head_revision"] == "20260511_03"
    assert result["missing_objects"] == []
    assert result["missing_submission_columns"] == []
