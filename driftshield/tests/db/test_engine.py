import pytest
from sqlalchemy import text
from driftshield.db.engine import get_engine, get_session_factory, get_db_url


def test_get_db_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    assert get_db_url() == "postgresql://user:pass@localhost:5432/testdb"


def test_get_db_url_default():
    # With no env var, returns default local dev URL
    url = get_db_url()
    assert "postgresql" in url
    assert "driftshield" in url


def test_get_engine_returns_engine():
    engine = get_engine("sqlite:///:memory:")
    assert engine is not None
    assert engine.url.drivername == "sqlite"


def test_get_session_factory_produces_sessions():
    engine = get_engine("sqlite:///:memory:")
    SessionLocal = get_session_factory(engine)
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1"))
        assert result.scalar() == 1
