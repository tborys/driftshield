from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


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
