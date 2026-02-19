from collections.abc import Generator

from sqlalchemy.orm import Session as DBSession

from driftshield.db.engine import get_engine, get_session_factory

_engine = None
_session_factory = None


def get_db() -> Generator[DBSession, None, None]:
    global _engine, _session_factory
    if _engine is None:
        _engine = get_engine()
        _session_factory = get_session_factory(_engine)
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
