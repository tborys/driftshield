# Phase 10: Database Models and Persistence — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add PostgreSQL persistence layer with SQLAlchemy ORM models for the 5 core tables and a PersistenceService that maps AnalysisResult to/from the database.

**Architecture:** SQLAlchemy 2.0 with mapped_column declarative style. Alembic for migrations. PersistenceService as a thin layer between the analysis engine and the database. The core engine remains pure (no DB knowledge).

**Tech Stack:** SQLAlchemy 2.0, Alembic, PostgreSQL 16, psycopg2-binary, pytest with testcontainers-postgres

**Design doc:** `docs/plans/2025-02-19-phases-10-14-design.md` (Phase 10 section)

---

## Task 10.1: Database Engine and Session Factory

**Files:**
- Create: `src/driftshield/db/__init__.py`
- Create: `src/driftshield/db/engine.py`
- Create: `tests/db/__init__.py`
- Create: `tests/db/test_engine.py`

**Step 1: Write the failing test**

```python
# tests/db/test_engine.py
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
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_engine.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# src/driftshield/db/__init__.py
```

```python
# src/driftshield/db/engine.py
import os

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

DEFAULT_DATABASE_URL = "postgresql://drift:drift@localhost:5432/driftshield"


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine(url: str | None = None) -> Engine:
    db_url = url or get_db_url()
    return create_engine(db_url, echo=False, pool_pre_ping=True)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_engine.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/ tests/db/
git commit -m "feat(db): add database engine and session factory"
```

---

## Task 10.2: ORM Base and Sessions Table

**Files:**
- Create: `src/driftshield/db/models.py`
- Create: `tests/db/test_models.py`

**Step 1: Write the failing test**

```python
# tests/db/test_models.py
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.models import Base, SessionModel


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_session_model(db_session):
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    s = SessionModel(
        id=session_id,
        external_id="ext-123",
        agent_id="claude-code",
        started_at=now,
        status="completed",
        metadata_json={"source": "test"},
    )
    db_session.add(s)
    db_session.commit()

    loaded = db_session.get(SessionModel, session_id)
    assert loaded is not None
    assert loaded.external_id == "ext-123"
    assert loaded.agent_id == "claude-code"
    assert loaded.status == "completed"
    assert loaded.metadata_json == {"source": "test"}


def test_session_model_defaults(db_session):
    s = SessionModel(
        id=uuid.uuid4(),
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db_session.add(s)
    db_session.commit()
    assert s.external_id is None
    assert s.agent_id is None
    assert s.metadata_json is None
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# src/driftshield/db/models.py
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, JSON, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Note: Using `JSON` (not `JSONB`) for SQLite test compatibility. The Alembic migration (Task 10.6) will use `JSONB` for the actual PostgreSQL column.

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/models.py tests/db/test_models.py
git commit -m "feat(db): add ORM base and sessions table model"
```

---

## Task 10.3: Decision Nodes Table

**Files:**
- Modify: `src/driftshield/db/models.py`
- Modify: `tests/db/test_models.py`

**Step 1: Write the failing test**

Add to `tests/db/test_models.py`:

```python
from driftshield.db.models import Base, SessionModel, DecisionNodeModel


def test_create_decision_node(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    node_id = uuid.uuid4()
    node = DecisionNodeModel(
        id=node_id,
        session_id=session_id,
        parent_node_id=None,
        sequence_num=1,
        timestamp=datetime.now(timezone.utc),
        event_type="TOOL_CALL",
        action="read_file",
        inputs={"path": "/etc/config"},
        outputs={"content": "..."},
        assumption_mutation=False,
        policy_divergence=False,
        constraint_violation=False,
        context_contamination=False,
        coverage_gap=True,
        is_inflection_node=False,
    )
    db_session.add(node)
    db_session.commit()

    loaded = db_session.get(DecisionNodeModel, node_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.event_type == "TOOL_CALL"
    assert loaded.coverage_gap is True
    assert loaded.assumption_mutation is False


def test_decision_node_parent_child(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    now = datetime.now(timezone.utc)
    parent = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, sequence_num=1,
        timestamp=now, event_type="TOOL_CALL", action="start",
    )
    child = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, parent_node_id=parent.id,
        sequence_num=2, timestamp=now, event_type="TOOL_CALL", action="next",
    )
    db_session.add_all([parent, child])
    db_session.commit()

    loaded_child = db_session.get(DecisionNodeModel, child.id)
    assert loaded_child.parent_node_id == parent.id
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py::test_create_decision_node -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `src/driftshield/db/models.py`:

```python
from sqlalchemy import String, DateTime, JSON, Boolean, Integer, ForeignKey


class DecisionNodeModel(Base):
    __tablename__ = "decision_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("decision_nodes.id"), nullable=True, index=True
    )
    sequence_num: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Risk flags
    assumption_mutation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    policy_divergence: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    constraint_violation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    context_contamination: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    coverage_gap: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    is_inflection_node: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/models.py tests/db/test_models.py
git commit -m "feat(db): add decision_nodes table model"
```

---

## Task 10.4: Recurrence Signatures and Session Signatures Tables

**Files:**
- Modify: `src/driftshield/db/models.py`
- Modify: `tests/db/test_models.py`

**Step 1: Write the failing test**

Add to `tests/db/test_models.py`:

```python
from driftshield.db.models import (
    Base, SessionModel, DecisionNodeModel,
    RecurrenceSignatureModel, SessionSignatureModel,
)


def test_create_recurrence_signature(db_session):
    sig_id = uuid.uuid4()
    sig = RecurrenceSignatureModel(
        id=sig_id,
        signature_hash="abc123def456",
        pattern={"sequence": ["TOOL_CALL", "BRANCH", "OUTPUT"]},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        occurrence_count=3,
        severity="medium",
    )
    db_session.add(sig)
    db_session.commit()

    loaded = db_session.get(RecurrenceSignatureModel, sig_id)
    assert loaded.signature_hash == "abc123def456"
    assert loaded.occurrence_count == 3
    assert loaded.severity == "medium"


def test_session_signature_junction(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    sig_id = uuid.uuid4()
    sig = RecurrenceSignatureModel(
        id=sig_id,
        signature_hash="hash1",
        pattern={},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        occurrence_count=1,
        severity="low",
    )
    db_session.add_all([s, sig])
    db_session.flush()

    node_id = uuid.uuid4()
    junction = SessionSignatureModel(
        session_id=session_id,
        signature_id=sig_id,
        matched_nodes=[str(node_id)],
    )
    db_session.add(junction)
    db_session.commit()

    loaded = db_session.query(SessionSignatureModel).first()
    assert loaded.session_id == session_id
    assert loaded.signature_id == sig_id
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py::test_create_recurrence_signature -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `src/driftshield/db/models.py`:

```python
class RecurrenceSignatureModel(Base):
    __tablename__ = "recurrence_signatures"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signature_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    pattern: Mapped[dict] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="low")


class SessionSignatureModel(Base):
    __tablename__ = "session_signatures"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), primary_key=True
    )
    signature_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("recurrence_signatures.id"), primary_key=True
    )
    matched_nodes: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

Note: `matched_nodes` uses `JSON` (list of UUID strings) instead of `UUID[]` ARRAY for SQLite test compatibility. The Alembic migration will use `ARRAY(PG_UUID)` for PostgreSQL.

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/models.py tests/db/test_models.py
git commit -m "feat(db): add recurrence signatures and session signatures tables"
```

---

## Task 10.5: Reports Table

**Files:**
- Modify: `src/driftshield/db/models.py`
- Modify: `tests/db/test_models.py`

**Step 1: Write the failing test**

Add to `tests/db/test_models.py`:

```python
from driftshield.db.models import (
    Base, SessionModel, DecisionNodeModel,
    RecurrenceSignatureModel, SessionSignatureModel, ReportModel,
)


def test_create_report(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    report_id = uuid.uuid4()
    report = ReportModel(
        id=report_id,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Report\n\nSample report content.",
        content_json={"sections": []},
        generated_by="system",
    )
    db_session.add(report)
    db_session.commit()

    loaded = db_session.get(ReportModel, report_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.report_type == "full"
    assert "Sample report content" in loaded.content_markdown
    assert loaded.content_json == {"sections": []}
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py::test_create_report -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `src/driftshield/db/models.py`:

```python
from sqlalchemy import Text


class ReportModel(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String, nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_models.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/models.py tests/db/test_models.py
git commit -m "feat(db): add reports table model"
```

---

## Task 10.6: Alembic Setup and Initial Migration

**Files:**
- Create: `src/driftshield/db/migrations/env.py`
- Create: `src/driftshield/db/migrations/script.py.mako`
- Create: `alembic.ini`

**Step 1: Initialise Alembic**

```bash
cd .worktrees/driftshield-v1/driftshield
python -m alembic init src/driftshield/db/migrations
```

**Step 2: Configure alembic.ini**

Edit `alembic.ini`:
- Set `script_location = src/driftshield/db/migrations`
- Set `sqlalchemy.url = postgresql://drift:drift@localhost:5432/driftshield`

**Step 3: Configure env.py**

Replace `src/driftshield/db/migrations/env.py` target_metadata with:

```python
import os
from driftshield.db.models import Base

target_metadata = Base.metadata

# Override URL from environment
config = context.config
db_url = os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
```

**Step 4: Generate initial migration**

```bash
cd .worktrees/driftshield-v1/driftshield
python -m alembic revision --autogenerate -m "initial schema - 5 core tables"
```

**Step 5: Review the generated migration**

Check the generated file in `src/driftshield/db/migrations/versions/`. Verify it creates all 5 tables with correct column types. Manually adjust:
- Change `JSON` to `JSONB` for PostgreSQL columns (metadata_json, inputs, outputs, pattern, content_json)
- Change `matched_nodes JSON` to `ARRAY(UUID)` for session_signatures
- Add composite index on `(session_id, sequence_num)` for decision_nodes

**Step 6: Commit**

```bash
git add alembic.ini src/driftshield/db/migrations/
git commit -m "feat(db): add Alembic setup and initial migration"
```

---

## Task 10.7: PersistenceService — Save AnalysisResult

**Files:**
- Create: `src/driftshield/db/persistence.py`
- Create: `tests/db/test_persistence.py`

**Step 1: Write the failing test**

```python
# tests/db/test_persistence.py
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.core.models import (
    CanonicalEvent, EventType, RiskClassification, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.db.models import Base, SessionModel, DecisionNodeModel
from driftshield.db.persistence import PersistenceService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_analysis_result():
    """Create a minimal AnalysisResult from two events."""
    session_id = uuid.uuid4()
    event1 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="read_file",
        inputs={"path": "/test"},
        outputs={"content": "data"},
    )
    event2 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.OUTPUT,
        agent_id="test-agent",
        action="respond",
        parent_event_id=event1.id,
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event1, event2])
    return result, domain_session


def test_save_analysis_result(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions = db_session.query(SessionModel).all()
    assert len(sessions) == 1
    assert sessions[0].agent_id == "test-agent"

    nodes = db_session.query(DecisionNodeModel).all()
    assert len(nodes) == 2
    assert nodes[0].session_id == domain_session.id
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py::test_save_analysis_result -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# src/driftshield/db/persistence.py
from sqlalchemy.orm import Session as DBSession

from driftshield.core.models import Session as DomainSession
from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.models import DecisionNode
from driftshield.db.models import SessionModel, DecisionNodeModel


class PersistenceService:
    def __init__(self, db: DBSession):
        self._db = db

    def save(self, session: DomainSession, result: AnalysisResult) -> SessionModel:
        session_model = SessionModel(
            id=session.id,
            external_id=session.external_id if hasattr(session, "external_id") else None,
            agent_id=session.agent_id,
            started_at=session.started_at,
            ended_at=session.ended_at if hasattr(session, "ended_at") else None,
            status=session.status.value,
            metadata_json=session.metadata if hasattr(session, "metadata") else None,
        )
        self._db.add(session_model)
        self._db.flush()

        for node in result.graph.nodes:
            risk = node.event.risk_classification or _empty_risk()
            node_model = DecisionNodeModel(
                id=node.id,
                session_id=session.id,
                parent_node_id=node.event.parent_event_id,
                sequence_num=node.sequence_num,
                timestamp=node.event.timestamp,
                event_type=node.event_type.value,
                action=node.action,
                inputs=node.inputs,
                outputs=node.outputs,
                metadata_json=node.event.metadata,
                assumption_mutation=risk.assumption_mutation,
                policy_divergence=risk.policy_divergence,
                constraint_violation=risk.constraint_violation,
                context_contamination=risk.context_contamination,
                coverage_gap=risk.coverage_gap,
                is_inflection_node=(
                    result.inflection_node is not None
                    and node.id == result.inflection_node.id
                ),
            )
            self._db.add(node_model)

        return session_model


def _empty_risk():
    from driftshield.core.models import RiskClassification
    return RiskClassification()
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/db/persistence.py tests/db/test_persistence.py
git commit -m "feat(db): add PersistenceService to save AnalysisResult"
```

---

## Task 10.8: PersistenceService — Load Session and Graph

**Files:**
- Modify: `src/driftshield/db/persistence.py`
- Modify: `tests/db/test_persistence.py`

**Step 1: Write the failing test**

Add to `tests/db/test_persistence.py`:

```python
def test_load_session(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    loaded = service.load_session(domain_session.id)
    assert loaded is not None
    assert loaded.id == domain_session.id
    assert loaded.agent_id == "test-agent"


def test_load_graph(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    graph = service.load_graph(domain_session.id)
    assert graph is not None
    assert len(graph.nodes) == 2


def test_load_nonexistent_session(db_session):
    service = PersistenceService(db_session)
    loaded = service.load_session(uuid.uuid4())
    assert loaded is None
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py::test_load_session -v`
Expected: FAIL with AttributeError

**Step 3: Write minimal implementation**

Add to `PersistenceService` in `src/driftshield/db/persistence.py`:

```python
from driftshield.core.models import (
    CanonicalEvent, EventType, RiskClassification, Session as DomainSession, SessionStatus,
)
from driftshield.core.graph.models import LineageGraph
from driftshield.core.graph.builder import build_graph


def load_session(self, session_id: uuid.UUID) -> DomainSession | None:
    model = self._db.get(SessionModel, session_id)
    if model is None:
        return None
    return DomainSession(
        id=model.id,
        agent_id=model.agent_id or "",
        started_at=model.started_at,
        status=SessionStatus(model.status),
    )

def load_graph(self, session_id: uuid.UUID) -> LineageGraph | None:
    nodes = (
        self._db.query(DecisionNodeModel)
        .filter(DecisionNodeModel.session_id == session_id)
        .order_by(DecisionNodeModel.sequence_num)
        .all()
    )
    if not nodes:
        return None

    events = [_node_model_to_event(n, session_id) for n in nodes]
    return build_graph(events, session_id)


def _node_model_to_event(node: DecisionNodeModel, session_id) -> CanonicalEvent:
    return CanonicalEvent(
        id=node.id,
        session_id=session_id,
        timestamp=node.timestamp,
        event_type=EventType(node.event_type),
        agent_id="",
        action=node.action,
        parent_event_id=node.parent_node_id,
        inputs=node.inputs,
        outputs=node.outputs,
        metadata=node.metadata_json,
        risk_classification=RiskClassification(
            assumption_mutation=node.assumption_mutation,
            policy_divergence=node.policy_divergence,
            constraint_violation=node.constraint_violation,
            context_contamination=node.context_contamination,
            coverage_gap=node.coverage_gap,
        ),
    )
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/persistence.py tests/db/test_persistence.py
git commit -m "feat(db): add load_session and load_graph to PersistenceService"
```

---

## Task 10.9: PersistenceService — List Sessions

**Files:**
- Modify: `src/driftshield/db/persistence.py`
- Modify: `tests/db/test_persistence.py`

**Step 1: Write the failing test**

Add to `tests/db/test_persistence.py`:

```python
def test_list_sessions(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=20)
    assert total == 1
    assert len(sessions) == 1
    assert sessions[0].id == domain_session.id


def test_list_sessions_pagination(db_session):
    service = PersistenceService(db_session)
    now = datetime.now(timezone.utc)
    for i in range(5):
        s = SessionModel(
            id=uuid.uuid4(), started_at=now, status="completed", agent_id=f"agent-{i}"
        )
        db_session.add(s)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=2)
    assert total == 5
    assert len(sessions) == 2

    sessions, total = service.list_sessions(page=3, per_page=2)
    assert total == 5
    assert len(sessions) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py::test_list_sessions -v`
Expected: FAIL with AttributeError

**Step 3: Write minimal implementation**

Add to `PersistenceService`:

```python
def list_sessions(
    self, page: int = 1, per_page: int = 20
) -> tuple[list[SessionModel], int]:
    query = self._db.query(SessionModel).order_by(SessionModel.started_at.desc())
    total = query.count()
    offset = (page - 1) * per_page
    sessions = query.offset(offset).limit(per_page).all()
    return sessions, total
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/db/test_persistence.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add src/driftshield/db/persistence.py tests/db/test_persistence.py
git commit -m "feat(db): add list_sessions with pagination to PersistenceService"
```

---

## Task 10.10: Docker Compose for Dev Database

**Files:**
- Create: `docker-compose.dev.yml` (or add db service to existing compose)

**Step 1: Create dev compose file**

```yaml
# docker-compose.dev.yml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: drift
      POSTGRES_PASSWORD: drift
      POSTGRES_DB: driftshield
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

**Step 2: Test it works**

```bash
cd .worktrees/driftshield-v1/driftshield
docker compose -f docker-compose.dev.yml up -d
# Wait for startup
sleep 3
docker compose -f docker-compose.dev.yml exec db pg_isready -U drift
# Expected: "accepting connections"
```

**Step 3: Run Alembic migration against real PostgreSQL**

```bash
DATABASE_URL=postgresql://drift:drift@localhost:5432/driftshield \
  python -m alembic upgrade head
```

**Step 4: Verify tables exist**

```bash
docker compose -f docker-compose.dev.yml exec db \
  psql -U drift -d driftshield -c "\dt"
```

Expected: 5 tables listed (sessions, decision_nodes, recurrence_signatures, session_signatures, reports) plus alembic_version.

**Step 5: Commit**

```bash
git add docker-compose.dev.yml
git commit -m "chore: add dev Docker Compose with PostgreSQL"
```

---

## Task 10.11: Integration Test with PostgreSQL

**Files:**
- Create: `tests/db/test_persistence_integration.py`

**Step 1: Write integration test**

This test requires a running PostgreSQL instance (from docker-compose.dev.yml). Mark it so it can be skipped in CI without Postgres.

```python
# tests/db/test_persistence_integration.py
"""Integration tests that require a running PostgreSQL instance.

Run: docker compose -f docker-compose.dev.yml up -d
Then: pytest tests/db/test_persistence_integration.py -v
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.db.models import Base
from driftshield.db.persistence import PersistenceService

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", "postgresql://drift:drift@localhost:5432/driftshield"
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 and start PostgreSQL to run",
)


@pytest.fixture
def pg_session():
    engine = create_engine(POSTGRES_URL)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()


def test_roundtrip_save_and_load(pg_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="integration-test",
        action="test_action",
        inputs={"key": "value"},
        outputs={"result": "ok"},
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="integration-test",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event])
    service = PersistenceService(pg_session)
    service.save(domain_session, result)
    pg_session.commit()

    loaded = service.load_session(session_id)
    assert loaded is not None
    assert loaded.agent_id == "integration-test"

    graph = service.load_graph(session_id)
    assert len(graph.nodes) == 1
    assert graph.nodes[0].action == "test_action"
```

**Step 2: Run test (requires Postgres)**

```bash
cd .worktrees/driftshield-v1/driftshield
RUN_INTEGRATION_TESTS=1 python -m pytest tests/db/test_persistence_integration.py -v
```

Expected: PASS

**Step 3: Commit**

```bash
git add tests/db/test_persistence_integration.py
git commit -m "test(db): add PostgreSQL integration test for persistence roundtrip"
```
