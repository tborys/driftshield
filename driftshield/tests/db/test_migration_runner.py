from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

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


@pytest.mark.parametrize("exists", [True, False])
def test_verify_row_exists_returns_expected_payload(monkeypatch, migration_runner_module, exists):
    class FakeResult:
        def scalar(self):
            return exists

    class FakeConnection:
        def execute(self, statement, params):
            assert "from installations" in str(statement)
            assert params == {"row_id": "00000000-0000-0000-0000-000000000551"}
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    monkeypatch.setattr(migration_runner_module, "create_engine", lambda *args, **kwargs: FakeEngine())

    result = migration_runner_module._verify_row_exists(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "installations",
        "00000000-0000-0000-0000-000000000551",
    )

    assert result == {
        "status": "ok",
        "mode": "verify_row_exists",
        "exists": exists,
        "table": "installations",
        "row_id": "00000000-0000-0000-0000-000000000551",
    }


def test_verify_row_exists_rejects_unsupported_table(migration_runner_module):
    result = migration_runner_module._verify_row_exists(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "bogus_table",
        "00000000-0000-0000-0000-000000000000",
    )

    assert result == {
        "status": "error",
        "mode": "verify_row_exists",
        "reason": "unsupported table for row verification: bogus_table",
        "table": "bogus_table",
        "row_id": "00000000-0000-0000-0000-000000000000",
    }


def test_verify_row_exists_handler_rejects_missing_fields(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )

    result = migration_runner_module.handler({"mode": "verify_row_exists"}, None)

    assert result == {
        "status": "error",
        "mode": "verify_row_exists",
        "reason": "verify_row_exists requires string table and row_id fields",
    }


def test_verify_row_exists_handler_mode_bypasses_upgrade(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )
    monkeypatch.setattr(
        migration_runner_module,
        "_verify_row_exists",
        lambda database_url, table, row_id: {
            "status": "ok",
            "mode": "verify_row_exists",
            "exists": False,
            "table": table,
            "row_id": row_id,
        },
    )

    result = migration_runner_module.handler(
        {
            "mode": "verify_row_exists",
            "table": "installations",
            "row_id": "00000000-0000-0000-0000-000000000551",
        },
        None,
    )

    assert result == {
        "status": "ok",
        "mode": "verify_row_exists",
        "exists": False,
        "table": "installations",
        "row_id": "00000000-0000-0000-0000-000000000551",
    }


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


def test_verify_table_columns_returns_expected_payload(monkeypatch, migration_runner_module):
    class FakeResult:
        def all(self):
            return [
                SimpleNamespace(column_name="attempt_count", data_type="integer"),
                SimpleNamespace(column_name="claimed_by", data_type="text"),
            ]

    class FakeConnection:
        def execute(self, statement, params):
            assert "information_schema.columns" in str(statement)
            assert params == {
                "table": "submissions",
                "columns": ("attempt_count", "claimed_by"),
            }
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    monkeypatch.setattr(migration_runner_module, "create_engine", lambda *args, **kwargs: FakeEngine())

    result = migration_runner_module._verify_table_columns(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "submissions",
        ("attempt_count", "claimed_by"),
    )

    assert result == {
        "status": "ok",
        "mode": "verify_table_columns",
        "table": "submissions",
        "columns": [
            {"name": "attempt_count", "type": "integer"},
            {"name": "claimed_by", "type": "text"},
        ],
        "missing_columns": [],
    }


def test_verify_table_columns_rejects_unsupported_table(migration_runner_module):
    result = migration_runner_module._verify_table_columns(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "bogus_table",
        ("attempt_count",),
    )

    assert result == {
        "status": "error",
        "mode": "verify_table_columns",
        "reason": "unsupported table for column verification: bogus_table",
        "table": "bogus_table",
        "columns": ["attempt_count"],
    }


def test_verify_table_columns_handler_rejects_missing_fields(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )

    result = migration_runner_module.handler({"mode": "verify_table_columns", "table": "submissions"}, None)

    assert result == {
        "status": "error",
        "mode": "verify_table_columns",
        "reason": "verify_table_columns requires string table and non-empty string columns fields",
    }


def test_verify_table_columns_handler_mode_bypasses_upgrade(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )
    monkeypatch.setattr(
        migration_runner_module,
        "_verify_table_columns",
        lambda database_url, table, columns: {
            "status": "ok",
            "mode": "verify_table_columns",
            "table": table,
            "columns": [{"name": "attempt_count", "type": "integer"}],
            "missing_columns": [column_name for column_name in columns if column_name != "attempt_count"],
        },
    )

    result = migration_runner_module.handler(
        {
            "mode": "verify_table_columns",
            "table": "submissions",
            "columns": ["attempt_count", "claimed_by"],
        },
        None,
    )

    assert result == {
        "status": "ok",
        "mode": "verify_table_columns",
        "table": "submissions",
        "columns": [{"name": "attempt_count", "type": "integer"}],
        "missing_columns": ["claimed_by"],
    }


def test_verify_query_returns_expected_payload(monkeypatch, migration_runner_module):
    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": UUID("11111111-1111-1111-1111-111111111111"),
                    "submission_id": "sub_demo",
                    "received_at": datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
                    "envelope": {"summary": "safe"},
                }
            ]

    class FakeConnection:
        def execute(self, statement, params):
            assert "select * from submissions where submission_id = 'sub_demo' limit :limit" in str(statement)
            assert params == {"limit": 5}
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    monkeypatch.setattr(migration_runner_module, "create_engine", lambda *args, **kwargs: FakeEngine())

    result = migration_runner_module._verify_query(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "submissions",
        "submission_id = 'sub_demo'",
        5,
    )

    assert result == {
        "status": "ok",
        "mode": "verify_query",
        "table": "submissions",
        "rows": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "submission_id": "sub_demo",
                "received_at": "2026-05-14T10:00:00+00:00",
                "envelope": {"summary": "safe"},
            }
        ],
        "count": 1,
    }


def test_verify_query_rejects_unsupported_table(migration_runner_module):
    result = migration_runner_module._verify_query(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "bogus_table",
        "1 = 1",
        1,
    )

    assert result == {
        "status": "error",
        "mode": "verify_query",
        "reason": "unsupported table for query verification: bogus_table",
        "table": "bogus_table",
    }


def test_verify_query_rejects_non_select_fragments(migration_runner_module):
    result = migration_runner_module._verify_query(
        "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
        "submissions",
        "1 = 1; delete from submissions",
        1,
    )

    assert result == {
        "status": "error",
        "mode": "verify_query",
        "reason": "verify_query accepts read-only SELECT filters only",
        "table": "submissions",
    }


def test_verify_query_handler_rejects_missing_fields(monkeypatch, migration_runner_module):
    monkeypatch.setattr(
        migration_runner_module,
        "_resolve_database_url",
        lambda: "postgresql+psycopg2://runner:secret@db.example.internal:5432/driftshield",
    )

    result = migration_runner_module.handler({"mode": "verify_query", "table": "submissions"}, None)

    assert result == {
        "status": "error",
        "mode": "verify_query",
        "reason": "verify_query requires string table, string where, and integer limit fields",
    }
