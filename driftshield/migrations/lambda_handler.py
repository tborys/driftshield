"""Migration runner entrypoint.

Runs `alembic upgrade head` against a PostgreSQL database. Designed to run
inside the migrations container image, either locally or as an AWS Lambda
function. Configuration is via environment variables only.

Required: exactly one of DATABASE_URL or DB_SECRET_ARN.

DATABASE_URL
    A SQLAlchemy-compatible PostgreSQL URL. Used as-is.

DB_SECRET_ARN
    An AWS Secrets Manager ARN. The secret value must be JSON containing
    `username`, `password`, `host`, `port`, and `dbname` (or `database` as
    an alias for `dbname`).

The handler returns a payload describing the starting and resulting head
revisions. On error it raises so the Lambda invocation fails visibly.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL, make_url

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ALEMBIC_INI_PATH = Path(__file__).resolve().parent / "alembic.ini"

REQUIRED_SECRET_KEYS = ("username", "password", "host", "port")
PHASE3H_REQUIRED_OBJECTS = (
    "entitlements",
    "service_identities",
    "team_pattern_summary",
    "team_recurrence_summary",
    "tenants",
    "workspaces",
)
PHASE3H_REQUIRED_SUBMISSIONS_COLUMNS = (
    "attempt_count",
    "claimed_by",
    "evidence_artifact_prefix",
    "project_reference",
    "service_identity_id",
    "tenant_id",
    "workflow_reference",
    "workspace_id",
)
VERIFY_ROW_EXISTS_ALLOWED_TABLES = (
    "installations",
    "consent_records",
)
VERIFY_TABLE_COLUMNS_ALLOWED_TABLES = (
    "submissions",
)


class MigrationRunnerError(RuntimeError):
    """Raised when configuration or migration execution fails."""


def _resolve_database_url() -> str:
    direct_url = os.environ.get("DATABASE_URL")
    secret_arn = os.environ.get("DB_SECRET_ARN")

    if direct_url and secret_arn:
        raise MigrationRunnerError(
            "Set exactly one of DATABASE_URL or DB_SECRET_ARN, not both."
        )

    if direct_url:
        return direct_url

    if not secret_arn:
        raise MigrationRunnerError(
            "Set DATABASE_URL or DB_SECRET_ARN. Neither was provided."
        )

    return _build_url_from_secret(secret_arn)


def _build_url_from_secret(secret_arn: str) -> str:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MigrationRunnerError(
            "DB_SECRET_ARN is set but boto3 is not installed. "
            "Install boto3 in the runner environment."
        ) from exc

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client = boto3.client("secretsmanager", region_name=region) if region else boto3.client("secretsmanager")

    response = client.get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString")
    if not raw:
        raise MigrationRunnerError("Secret value is empty or binary; expected JSON string.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationRunnerError("Secret value is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise MigrationRunnerError("Secret JSON must be an object.")

    missing = [key for key in REQUIRED_SECRET_KEYS if key not in payload]
    dbname = payload.get("dbname") or payload.get("database")
    if not dbname:
        missing.append("dbname")

    if missing:
        raise MigrationRunnerError(
            f"Secret JSON is missing required keys: {sorted(set(missing))}."
        )

    username = payload["username"]
    password = payload["password"]
    host = payload["host"]
    port = payload["port"]

    try:
        parsed_port = int(port)
    except (TypeError, ValueError) as exc:
        raise MigrationRunnerError("Secret JSON field 'port' must be an integer.") from exc

    return URL.create(
        "postgresql+psycopg2",
        username=str(username),
        password=str(password),
        host=str(host),
        port=parsed_port,
        database=str(dbname),
    ).render_as_string(hide_password=False)


def _build_alembic_config(database_url: str) -> Config:
    if not ALEMBIC_INI_PATH.exists():
        raise MigrationRunnerError(f"alembic.ini not found at {ALEMBIC_INI_PATH}.")

    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _current_revision(database_url: str) -> str | None:
    engine = create_engine(database_url, poolclass=None)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def _script_head(config: Config) -> str | None:
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    return head


def _verify_phase3h_objects(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, poolclass=None)
    try:
        with engine.connect() as connection:
            current_revision = MigrationContext.configure(connection).get_current_revision()
            object_rows = connection.execute(
                text(
                    """
                    select table_name, table_type
                    from information_schema.tables
                    where table_schema = 'public'
                      and table_name in :required_objects
                    order by table_name
                    """
                ).bindparams(bindparam("required_objects", expanding=True)),
                {"required_objects": PHASE3H_REQUIRED_OBJECTS},
            ).all()
            column_rows = connection.execute(
                text(
                    """
                    select column_name, data_type
                    from information_schema.columns
                    where table_schema = 'public'
                      and table_name = 'submissions'
                      and column_name in :required_columns
                    order by column_name
                    """
                ).bindparams(bindparam("required_columns", expanding=True)),
                {"required_columns": PHASE3H_REQUIRED_SUBMISSIONS_COLUMNS},
            ).all()
    finally:
        engine.dispose()

    found_objects = {row.table_name for row in object_rows}
    found_columns = {row.column_name for row in column_rows}

    return {
        "status": "ok",
        "mode": "verify_phase3h_objects",
        "head_revision": current_revision,
        "objects": [
            {"name": row.table_name, "type": row.table_type}
            for row in object_rows
        ],
        "submissions_columns": [
            {"name": row.column_name, "type": row.data_type}
            for row in column_rows
        ],
        "missing_objects": [
            name for name in PHASE3H_REQUIRED_OBJECTS if name not in found_objects
        ],
        "missing_submission_columns": [
            name
            for name in PHASE3H_REQUIRED_SUBMISSIONS_COLUMNS
            if name not in found_columns
        ],
    }


def _verify_row_exists(database_url: str, table: str, row_id: str) -> dict[str, Any]:
    if table not in VERIFY_ROW_EXISTS_ALLOWED_TABLES:
        return {
            "status": "error",
            "mode": "verify_row_exists",
            "reason": f"unsupported table for row verification: {table}",
            "table": table,
            "row_id": row_id,
        }

    engine = create_engine(database_url, poolclass=None)
    try:
        with engine.connect() as connection:
            exists = bool(
                connection.execute(
                    text(f"select exists(select 1 from {table} where id = cast(:row_id as uuid))"),
                    {"row_id": row_id},
                ).scalar()
            )
    finally:
        engine.dispose()

    return {
        "status": "ok",
        "mode": "verify_row_exists",
        "exists": exists,
        "table": table,
        "row_id": row_id,
    }


def _verify_table_columns(
    database_url: str,
    table: str,
    columns: tuple[str, ...],
) -> dict[str, Any]:
    if table not in VERIFY_TABLE_COLUMNS_ALLOWED_TABLES:
        return {
            "status": "error",
            "mode": "verify_table_columns",
            "reason": f"unsupported table for column verification: {table}",
            "table": table,
            "columns": list(columns),
        }

    engine = create_engine(database_url, poolclass=None)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    select column_name, data_type
                    from information_schema.columns
                    where table_schema = 'public'
                      and table_name = :table
                      and column_name in :columns
                    order by column_name
                    """
                ).bindparams(bindparam("columns", expanding=True)),
                {"table": table, "columns": columns},
            ).all()
    finally:
        engine.dispose()

    found_columns = {row.column_name for row in rows}
    return {
        "status": "ok",
        "mode": "verify_table_columns",
        "table": table,
        "columns": [
            {"name": row.column_name, "type": row.data_type}
            for row in rows
        ],
        "missing_columns": [
            column_name for column_name in columns if column_name not in found_columns
        ],
    }


def handler(event: Any, context: Any) -> dict[str, Any]:
    """Lambda entrypoint. Applies all pending migrations to the target DB."""

    del context

    try:
        database_url = _resolve_database_url()
    except MigrationRunnerError as exc:
        logger.error("configuration error: %s", exc)
        raise

    if isinstance(event, dict) and event.get("mode") == "verify_row_exists":
        table = event.get("table")
        row_id = event.get("row_id")
        if not isinstance(table, str) or not isinstance(row_id, str):
            return {
                "status": "error",
                "mode": "verify_row_exists",
                "reason": "verify_row_exists requires string table and row_id fields",
            }

        try:
            result = _verify_row_exists(database_url, table, row_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("row existence verification failed: %s", _redact(str(exc), database_url))
            raise MigrationRunnerError("Could not verify Aurora row existence.") from exc
        logger.info("row existence verification complete: %s", result)
        return result

    if isinstance(event, dict) and event.get("mode") == "verify_phase3h_objects":
        try:
            result = _verify_phase3h_objects(database_url)
        except Exception as exc:  # noqa: BLE001
            logger.error("phase 3h object verification failed: %s", _redact(str(exc), database_url))
            raise MigrationRunnerError("Could not verify Phase 3h Aurora objects.") from exc
        logger.info("phase 3h object verification complete: %s", result)
        return result

    if isinstance(event, dict) and event.get("mode") == "verify_table_columns":
        table = event.get("table")
        columns = event.get("columns")
        if (
            not isinstance(table, str)
            or not isinstance(columns, list)
            or not columns
            or any(not isinstance(column_name, str) for column_name in columns)
        ):
            return {
                "status": "error",
                "mode": "verify_table_columns",
                "reason": "verify_table_columns requires string table and non-empty string columns fields",
            }

        try:
            result = _verify_table_columns(database_url, table, tuple(columns))
        except Exception as exc:  # noqa: BLE001
            logger.error("table column verification failed: %s", _redact(str(exc), database_url))
            raise MigrationRunnerError("Could not verify Aurora table columns.") from exc
        logger.info("table column verification complete: %s", result)
        return result

    alembic_config = _build_alembic_config(database_url)

    try:
        starting_revision = _current_revision(database_url)
    except Exception as exc:  # noqa: BLE001 - re-raised below as a runner error
        logger.error("failed to read current revision: %s", _redact(str(exc), database_url))
        raise MigrationRunnerError("Could not read current Alembic revision before upgrade.") from exc

    target_head = _script_head(alembic_config)
    logger.info(
        "migration plan: starting_revision=%s target_head=%s",
        starting_revision,
        target_head,
    )

    try:
        command.upgrade(alembic_config, "head")
    except Exception as exc:  # noqa: BLE001 - all alembic errors are runner errors here
        message = _redact(str(exc), database_url)
        logger.error("alembic upgrade failed: %s", message)
        raise MigrationRunnerError(f"Alembic upgrade failed: {message}") from exc

    try:
        ending_revision = _current_revision(database_url)
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to read post-upgrade revision: %s", _redact(str(exc), database_url))
        raise MigrationRunnerError("Could not read Alembic revision after upgrade.") from exc

    result = {
        "status": "ok",
        "starting_revision": starting_revision,
        "head_revision": ending_revision,
        "target_head": target_head,
    }
    logger.info("migration complete: %s", result)
    return result


def _redact(message: str, database_url: str) -> str:
    """Strip the database URL from any string before it reaches logs or responses."""

    if not database_url:
        return message

    redacted = message.replace(database_url, "<redacted-database-url>")

    try:
        parsed = make_url(database_url)
    except Exception:  # noqa: BLE001 - best-effort redaction only
        return redacted

    password = parsed.password
    if password:
        redacted = redacted.replace(password, "<redacted>")
        redacted = redacted.replace(quote(password, safe=""), "<redacted>")

    rendered = parsed.render_as_string(hide_password=False)
    rendered_redacted = parsed.render_as_string(hide_password=True)
    redacted = redacted.replace(rendered, "<redacted-database-url>")
    redacted = redacted.replace(rendered_redacted, "<redacted-database-url>")
    return redacted
