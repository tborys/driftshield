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

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ALEMBIC_INI_PATH = Path(__file__).resolve().parent / "alembic.ini"

REQUIRED_SECRET_KEYS = ("username", "password", "host", "port")


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
        import boto3
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

    return f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{dbname}"


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


def handler(event: Any, context: Any) -> dict[str, Any]:
    """Lambda entrypoint. Applies all pending migrations to the target DB."""

    del event, context  # The runner ignores the invocation payload.

    try:
        database_url = _resolve_database_url()
    except MigrationRunnerError as exc:
        logger.error("configuration error: %s", exc)
        raise

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
    if "://" in database_url:
        scheme, rest = database_url.split("://", 1)
        if "@" in rest:
            credentials, host_part = rest.rsplit("@", 1)
            redacted = redacted.replace(f"{scheme}://{credentials}@", f"{scheme}://<redacted>@")
            if ":" in credentials:
                password = credentials.split(":", 1)[1]
                if password:
                    redacted = redacted.replace(password, "<redacted>")
    return redacted
