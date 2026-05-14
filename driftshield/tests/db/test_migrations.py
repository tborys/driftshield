from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from driftshield.db.hosted_schema_sql import (
    build_phase3h_oss_fallback_installation_seed_sql,
    build_phase3h_teams_ab_fixture_seed_sql,
    build_phase3h_tenant_oss_seed_sql,
)


def test_alembic_has_single_head():
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1


def test_recurrence_cleanup_downgrade_uses_sqlite_safe_types():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/driftshield/db/migrations/versions/9b3d7e1a4c2f_remove_recurrence_tables_from_oss.py"
    )
    spec = spec_from_file_location("migration_9b3d7e1a4c2f", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("sessions", metadata, sa.Column("id", sa.String(length=36), primary_key=True))

    with engine.begin() as connection:
        metadata.create_all(connection)

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.downgrade()

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert {"recurrence_signatures", "session_signatures"} <= tables

        recurrence_columns = {
            column["name"]: column for column in inspector.get_columns("recurrence_signatures")
        }
        session_columns = {
            column["name"]: column for column in inspector.get_columns("session_signatures")
        }

        assert isinstance(recurrence_columns["id"]["type"], sa.String)
        assert isinstance(session_columns["session_id"]["type"], sa.String)
        assert isinstance(session_columns["signature_id"]["type"], sa.String)


def test_phase3h_tenant_oss_seed_downgrade_is_forward_only() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/driftshield/db/migrations/versions/20260512_01_seed_tenant_oss.py"
    )
    spec = spec_from_file_location("migration_20260512_01", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(NotImplementedError, match="forward-only"):
        module.downgrade()


def test_phase3h_tenant_oss_seed_sql_is_idempotent_and_resolves_uuid() -> None:
    statements = build_phase3h_tenant_oss_seed_sql()

    assert len(statements) == 2
    assert "insert into tenants" in statements[0]
    assert "'tenant-oss'" in statements[0]
    assert "on conflict (tenant_id) do nothing" in statements[0].lower()
    assert "seed_revision" not in statements[0]
    assert statements[1].strip().lower() == "select id from tenants where tenant_id = 'tenant-oss'"


def test_phase3h_oss_fallback_installation_seed_downgrade_is_forward_only() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/driftshield/db/migrations/versions/20260512_02_seed_oss_fallback_installation.py"
    )
    spec = spec_from_file_location("migration_20260512_02", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(NotImplementedError, match="forward-only; restore from snapshot per #163 AC5"):
        module.downgrade()


def test_phase3h_oss_fallback_installation_seed_sql_is_idempotent_and_resolves_ids() -> None:
    statements = build_phase3h_oss_fallback_installation_seed_sql()

    assert len(statements) == 3
    assert "insert into installations" in statements[0].lower()
    assert "'oss-fallback-installation'" in statements[0]
    assert "'00000000-0000-0000-0000-000000000551'" in statements[0]
    assert "on conflict (installation_id) do nothing" in statements[0].lower()
    assert "insert into consent_records" in statements[1].lower()
    assert "'00000000-0000-0000-0000-000000000c51'" in statements[1]
    assert "on conflict (id) do nothing" in statements[1].lower()
    assert "select" in statements[2].lower()
    assert "installation_row_id" in statements[2]
    assert "consent_record_id" in statements[2]


def test_phase3h_teams_ab_fixture_seed_downgrade_is_forward_only() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/driftshield/db/migrations/versions/20260513_01_seed_teams_ab_fixtures.py"
    )
    spec = spec_from_file_location("migration_20260513_01", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(NotImplementedError, match="forward-only; restore from snapshot per #26 AC5"):
        module.downgrade()


def test_phase3h_teams_ab_fixture_seed_sql_is_idempotent_and_resolves_summary_rows() -> None:
    statements = build_phase3h_teams_ab_fixture_seed_sql()

    assert len(statements) == 10
    assert "insert into tenants" in statements[0].lower()
    assert "'tenant-alpha'" in statements[0]
    assert "'00000000-0000-0000-0000-000000000101'" in statements[0]
    assert "'tenant-beta'" in statements[0]
    assert "insert into workspaces" in statements[1].lower()
    assert "'workspace-alpha'" in statements[1]
    assert "'workspace-beta'" in statements[1]
    assert "insert into service_identities" in statements[2].lower()
    assert "'svc-alpha'" in statements[2]
    assert "'svc-beta'" in statements[2]
    assert "insert into entitlements" in statements[3].lower()
    assert "[\"teams:read\"]'::jsonb" in statements[3]
    assert "insert into submissions" in statements[6].lower()
    assert "'sub-alpha-4'" in statements[6]
    assert "'sub-beta-1'" in statements[6]
    assert "insert into trust_evaluations" in statements[7].lower()
    assert "'quarantined'" in statements[7]
    assert "insert into signature_matches" in statements[8].lower()
    assert "'grp:retry-loop'" in statements[8]
    assert "select" in statements[9].lower()
    assert "tenant_alpha_recurrence_summary_rows" in statements[9]
    assert "tenant_beta_pattern_summary_rows" in statements[9]


def test_submission_worker_columns_revision_applies_and_rolls_back_cleanly() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/driftshield/db/migrations/versions/20260514_01_add_submissions_worker_columns.py"
    )
    spec = spec_from_file_location("migration_20260514_01", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "submissions",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("submission_id", sa.String(length=64), nullable=False),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()

        inspector = sa.inspect(connection)
        columns_after_upgrade = {
            column["name"]: column for column in inspector.get_columns("submissions")
        }
        assert "attempt_count" in columns_after_upgrade
        assert "claimed_by" in columns_after_upgrade

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.downgrade()

        columns_after_downgrade = {
            column["name"]: column for column in sa.inspect(connection).get_columns("submissions")
        }
        assert "attempt_count" not in columns_after_downgrade
        assert "claimed_by" not in columns_after_downgrade
