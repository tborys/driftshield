# DriftShield V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a self-hosted forensic analysis platform that reconstructs autonomous AI reasoning as structured behavioural lineage graphs.

**Architecture:** Monolith-first (Python/FastAPI + React), PostgreSQL with recursive CTEs for graph storage, passive log ingestion with multiple parsers feeding a canonical event model.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, Alembic, PostgreSQL 15, React 18, TypeScript, Vite, Docker Compose

**Approach:** Core models + synthetic validation first. Prove the structural abstraction works before building full product. TDD throughout.

---

## Phase 1: Project Foundation

### Task 1.1: Project Structure Setup

**Files:**
- Create: `driftshield/pyproject.toml`
- Create: `driftshield/src/driftshield/__init__.py`
- Create: `driftshield/tests/__init__.py`
- Create: `driftshield/.gitignore`

**Step 1: Create project directory structure**

```bash
mkdir -p driftshield/src/driftshield
mkdir -p driftshield/tests
```

**Step 2: Create pyproject.toml**

```toml
[project]
name = "driftshield"
version = "0.1.0"
description = "AI Decision Forensics & Continuous Risk Infrastructure"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg2-binary>=2.9.9",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/driftshield"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
```

**Step 3: Create package init files**

```python
# src/driftshield/__init__.py
"""DriftShield - AI Decision Forensics."""

__version__ = "0.1.0"
```

```python
# tests/__init__.py
"""DriftShield test suite."""
```

**Step 4: Create .gitignore**

```
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.env
.venv/
venv/
*.db
*.sqlite
.coverage
htmlcov/
```

**Step 5: Verify setup**

```bash
cd driftshield
python -m pip install -e ".[dev]"
pytest --collect-only
```

Expected: "no tests ran" (collection succeeds, no tests yet)

**Step 6: Commit**

```bash
git add driftshield/
git commit -m "chore: initialise driftshield project structure"
```

---

## Phase 2: Core Domain Models

### Task 2.1: Event Types Enum

**Files:**
- Create: `driftshield/src/driftshield/core/__init__.py`
- Create: `driftshield/src/driftshield/core/models.py`
- Create: `driftshield/tests/core/__init__.py`
- Create: `driftshield/tests/core/test_models.py`

**Step 1: Create core package**

```bash
mkdir -p driftshield/src/driftshield/core
mkdir -p driftshield/tests/core
touch driftshield/src/driftshield/core/__init__.py
touch driftshield/tests/core/__init__.py
```

**Step 2: Write the failing test for EventType enum**

```python
# tests/core/test_models.py
"""Tests for core domain models."""

from driftshield.core.models import EventType


class TestEventType:
    def test_event_type_values_exist(self):
        """All expected event types are defined."""
        assert EventType.TOOL_CALL.value == "TOOL_CALL"
        assert EventType.BRANCH.value == "BRANCH"
        assert EventType.CONSTRAINT_CHECK.value == "CONSTRAINT_CHECK"
        assert EventType.ASSUMPTION.value == "ASSUMPTION"
        assert EventType.HANDOFF.value == "HANDOFF"
        assert EventType.OUTPUT.value == "OUTPUT"

    def test_event_type_is_string_enum(self):
        """EventType values are strings for JSON serialization."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)
```

**Step 3: Run test to verify it fails**

```bash
cd driftshield
pytest tests/core/test_models.py -v
```

Expected: FAIL with "cannot import name 'EventType'"

**Step 4: Write minimal implementation**

```python
# src/driftshield/core/models.py
"""Core domain models for DriftShield."""

from enum import Enum


class EventType(str, Enum):
    """Types of decision nodes in a reasoning trace."""

    TOOL_CALL = "TOOL_CALL"
    BRANCH = "BRANCH"
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"
    ASSUMPTION = "ASSUMPTION"
    HANDOFF = "HANDOFF"
    OUTPUT = "OUTPUT"
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/core/test_models.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add driftshield/
git commit -m "feat(core): add EventType enum"
```

---

### Task 2.2: RiskClassification Model

**Files:**
- Modify: `driftshield/src/driftshield/core/models.py`
- Modify: `driftshield/tests/core/test_models.py`

**Step 1: Write the failing test for RiskClassification**

```python
# Add to tests/core/test_models.py

from driftshield.core.models import EventType, RiskClassification


class TestRiskClassification:
    def test_default_values_are_false(self):
        """All risk flags default to False."""
        risk = RiskClassification()
        assert risk.assumption_mutation is False
        assert risk.policy_divergence is False
        assert risk.constraint_violation is False
        assert risk.context_contamination is False
        assert risk.coverage_gap is False

    def test_can_set_individual_flags(self):
        """Individual flags can be set to True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        assert risk.assumption_mutation is True
        assert risk.policy_divergence is False
        assert risk.coverage_gap is True

    def test_has_any_flag(self):
        """has_any_flag returns True if any flag is set."""
        assert RiskClassification().has_any_flag() is False
        assert RiskClassification(assumption_mutation=True).has_any_flag() is True
        assert RiskClassification(coverage_gap=True).has_any_flag() is True

    def test_active_flags_returns_set_flags(self):
        """active_flags returns list of flag names that are True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        active = risk.active_flags()
        assert "assumption_mutation" in active
        assert "coverage_gap" in active
        assert "policy_divergence" not in active
        assert len(active) == 2
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/test_models.py::TestRiskClassification -v
```

Expected: FAIL with "cannot import name 'RiskClassification'"

**Step 3: Write minimal implementation**

```python
# Add to src/driftshield/core/models.py

from dataclasses import dataclass, fields


@dataclass
class RiskClassification:
    """Risk flags for a decision node transition."""

    assumption_mutation: bool = False
    policy_divergence: bool = False
    constraint_violation: bool = False
    context_contamination: bool = False
    coverage_gap: bool = False

    def has_any_flag(self) -> bool:
        """Return True if any risk flag is set."""
        return any(getattr(self, f.name) for f in fields(self))

    def active_flags(self) -> list[str]:
        """Return list of flag names that are True."""
        return [f.name for f in fields(self) if getattr(self, f.name)]
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/test_models.py::TestRiskClassification -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(core): add RiskClassification model"
```

---

### Task 2.3: CanonicalEvent Model

**Files:**
- Modify: `driftshield/src/driftshield/core/models.py`
- Modify: `driftshield/tests/core/test_models.py`

**Step 1: Write the failing test for CanonicalEvent**

```python
# Add to tests/core/test_models.py

from datetime import datetime, timezone
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification


class TestCanonicalEvent:
    def test_create_minimal_event(self):
        """Can create event with required fields only."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="agent-1",
            action="fetch_data",
        )
        assert event.parent_event_id is None
        assert event.inputs == {}
        assert event.outputs == {}
        assert event.metadata == {}
        assert event.risk_classification is None

    def test_create_full_event(self):
        """Can create event with all fields."""
        parent_id = uuid4()
        event_id = uuid4()
        now = datetime.now(timezone.utc)

        event = CanonicalEvent(
            id=event_id,
            session_id="session-123",
            timestamp=now,
            event_type=EventType.BRANCH,
            agent_id="agent-1",
            parent_event_id=parent_id,
            action="decide_path",
            inputs={"options": ["a", "b"]},
            outputs={"chosen": "a"},
            metadata={"source": "test"},
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        assert event.id == event_id
        assert event.parent_event_id == parent_id
        assert event.inputs == {"options": ["a", "b"]}
        assert event.risk_classification.assumption_mutation is True

    def test_event_has_risk_flags(self):
        """has_risk_flags delegates to risk_classification."""
        event_no_risk = CanonicalEvent(
            id=uuid4(),
            session_id="s",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.OUTPUT,
            agent_id="a",
            action="x",
        )
        assert event_no_risk.has_risk_flags() is False

        event_with_risk = CanonicalEvent(
            id=uuid4(),
            session_id="s",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.OUTPUT,
            agent_id="a",
            action="x",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        assert event_with_risk.has_risk_flags() is True
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/test_models.py::TestCanonicalEvent -v
```

Expected: FAIL with "cannot import name 'CanonicalEvent'"

**Step 3: Write minimal implementation**

```python
# Add to src/driftshield/core/models.py

from datetime import datetime
from uuid import UUID


@dataclass
class CanonicalEvent:
    """A single decision node in a reasoning trace."""

    id: UUID
    session_id: str
    timestamp: datetime
    event_type: EventType
    agent_id: str
    action: str
    parent_event_id: UUID | None = None
    inputs: dict = None
    outputs: dict = None
    metadata: dict = None
    risk_classification: RiskClassification | None = None

    def __post_init__(self):
        if self.inputs is None:
            self.inputs = {}
        if self.outputs is None:
            self.outputs = {}
        if self.metadata is None:
            self.metadata = {}

    def has_risk_flags(self) -> bool:
        """Return True if this event has any risk flags set."""
        if self.risk_classification is None:
            return False
        return self.risk_classification.has_any_flag()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/test_models.py::TestCanonicalEvent -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(core): add CanonicalEvent model"
```

---

### Task 2.4: Session Model

**Files:**
- Modify: `driftshield/src/driftshield/core/models.py`
- Modify: `driftshield/tests/core/test_models.py`

**Step 1: Write the failing test for Session**

```python
# Add to tests/core/test_models.py

from driftshield.core.models import Session, SessionStatus


class TestSessionStatus:
    def test_status_values(self):
        """Session status enum has expected values."""
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.FAILED.value == "failed"


class TestSession:
    def test_create_session(self):
        """Can create a session with required fields."""
        session_id = uuid4()
        now = datetime.now(timezone.utc)

        session = Session(
            id=session_id,
            agent_id="doc-reviewer",
            started_at=now,
        )
        assert session.id == session_id
        assert session.external_id is None
        assert session.status == SessionStatus.RUNNING
        assert session.ended_at is None
        assert session.metadata == {}

    def test_create_completed_session(self):
        """Can create a completed session."""
        now = datetime.now(timezone.utc)

        session = Session(
            id=uuid4(),
            agent_id="doc-reviewer",
            started_at=now,
            ended_at=now,
            status=SessionStatus.COMPLETED,
            external_id="ext-123",
            metadata={"source": "langsmith"},
        )
        assert session.status == SessionStatus.COMPLETED
        assert session.external_id == "ext-123"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/test_models.py::TestSessionStatus -v
pytest tests/core/test_models.py::TestSession -v
```

Expected: FAIL with "cannot import name 'Session'"

**Step 3: Write minimal implementation**

```python
# Add to src/driftshield/core/models.py

class SessionStatus(str, Enum):
    """Status of an agent session."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Session:
    """An agent workflow execution containing decision nodes."""

    id: UUID
    agent_id: str
    started_at: datetime
    external_id: str | None = None
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.RUNNING
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/test_models.py::TestSession -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(core): add Session and SessionStatus models"
```

---

## Phase 3: Lineage Graph

### Task 3.1: DecisionNode (Graph Node Wrapper)

**Files:**
- Create: `driftshield/src/driftshield/core/graph/__init__.py`
- Create: `driftshield/src/driftshield/core/graph/models.py`
- Create: `driftshield/tests/core/graph/__init__.py`
- Create: `driftshield/tests/core/graph/test_models.py`

**Step 1: Create graph package**

```bash
mkdir -p driftshield/src/driftshield/core/graph
mkdir -p driftshield/tests/core/graph
touch driftshield/src/driftshield/core/graph/__init__.py
touch driftshield/tests/core/graph/__init__.py
```

**Step 2: Write the failing test for DecisionNode**

```python
# tests/core/graph/test_models.py
"""Tests for graph models."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.models import DecisionNode


def make_event(**kwargs) -> CanonicalEvent:
    """Factory for creating test events."""
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestDecisionNode:
    def test_create_from_event(self):
        """DecisionNode wraps a CanonicalEvent."""
        event = make_event(action="fetch_data")
        node = DecisionNode(event=event, sequence_num=1)

        assert node.event == event
        assert node.sequence_num == 1
        assert node.id == event.id
        assert node.action == "fetch_data"

    def test_node_delegates_to_event(self):
        """Node properties delegate to underlying event."""
        event = make_event(
            event_type=EventType.BRANCH,
            inputs={"x": 1},
            outputs={"y": 2},
        )
        node = DecisionNode(event=event, sequence_num=0)

        assert node.event_type == EventType.BRANCH
        assert node.inputs == {"x": 1}
        assert node.outputs == {"y": 2}
        assert node.parent_event_id == event.parent_event_id

    def test_has_risk_flags_delegates(self):
        """has_risk_flags delegates to event."""
        event_clean = make_event()
        node_clean = DecisionNode(event=event_clean, sequence_num=0)
        assert node_clean.has_risk_flags() is False

        event_risky = make_event(
            risk_classification=RiskClassification(assumption_mutation=True)
        )
        node_risky = DecisionNode(event=event_risky, sequence_num=0)
        assert node_risky.has_risk_flags() is True

    def test_is_inflection_node_default_false(self):
        """is_inflection_node defaults to False."""
        node = DecisionNode(event=make_event(), sequence_num=0)
        assert node.is_inflection_node is False

    def test_can_mark_as_inflection(self):
        """Can mark node as inflection point."""
        node = DecisionNode(event=make_event(), sequence_num=0, is_inflection_node=True)
        assert node.is_inflection_node is True
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/core/graph/test_models.py -v
```

Expected: FAIL with "cannot import name 'DecisionNode'"

**Step 4: Write minimal implementation**

```python
# src/driftshield/core/graph/models.py
"""Graph models for behavioral lineage."""

from dataclasses import dataclass
from uuid import UUID

from driftshield.core.models import CanonicalEvent, EventType


@dataclass
class DecisionNode:
    """A node in the behavioral lineage graph, wrapping a CanonicalEvent."""

    event: CanonicalEvent
    sequence_num: int
    is_inflection_node: bool = False

    @property
    def id(self) -> UUID:
        return self.event.id

    @property
    def action(self) -> str:
        return self.event.action

    @property
    def event_type(self) -> EventType:
        return self.event.event_type

    @property
    def inputs(self) -> dict:
        return self.event.inputs

    @property
    def outputs(self) -> dict:
        return self.event.outputs

    @property
    def parent_event_id(self) -> UUID | None:
        return self.event.parent_event_id

    def has_risk_flags(self) -> bool:
        return self.event.has_risk_flags()
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/core/graph/test_models.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add driftshield/
git commit -m "feat(graph): add DecisionNode model"
```

---

### Task 3.2: LineageGraph Construction

**Files:**
- Modify: `driftshield/src/driftshield/core/graph/models.py`
- Modify: `driftshield/tests/core/graph/test_models.py`

**Step 1: Write the failing test for LineageGraph**

```python
# Add to tests/core/graph/test_models.py

from driftshield.core.graph.models import DecisionNode, LineageGraph


class TestLineageGraph:
    def test_create_empty_graph(self):
        """Can create an empty graph."""
        graph = LineageGraph(session_id="test-session")
        assert graph.session_id == "test-session"
        assert len(graph.nodes) == 0

    def test_add_node(self):
        """Can add nodes to graph."""
        graph = LineageGraph(session_id="test-session")
        event = make_event()
        node = DecisionNode(event=event, sequence_num=0)

        graph.add_node(node)

        assert len(graph.nodes) == 1
        assert graph.get_node(event.id) == node

    def test_get_node_by_id(self):
        """Can retrieve node by ID."""
        graph = LineageGraph(session_id="test-session")
        event = make_event()
        node = DecisionNode(event=event, sequence_num=0)
        graph.add_node(node)

        retrieved = graph.get_node(event.id)
        assert retrieved == node

    def test_get_nonexistent_node_returns_none(self):
        """Getting nonexistent node returns None."""
        graph = LineageGraph(session_id="test-session")
        assert graph.get_node(uuid4()) is None

    def test_nodes_in_sequence_order(self):
        """nodes property returns nodes in sequence order."""
        graph = LineageGraph(session_id="test-session")

        event1 = make_event(action="first")
        event2 = make_event(action="second")
        event3 = make_event(action="third")

        graph.add_node(DecisionNode(event=event2, sequence_num=1))
        graph.add_node(DecisionNode(event=event1, sequence_num=0))
        graph.add_node(DecisionNode(event=event3, sequence_num=2))

        nodes = graph.nodes
        assert [n.action for n in nodes] == ["first", "second", "third"]

    def test_root_node(self):
        """root property returns node with sequence_num 0."""
        graph = LineageGraph(session_id="test-session")

        event1 = make_event(action="root")
        event2 = make_event(action="child", parent_event_id=event1.id)

        graph.add_node(DecisionNode(event=event1, sequence_num=0))
        graph.add_node(DecisionNode(event=event2, sequence_num=1))

        assert graph.root.action == "root"

    def test_root_none_for_empty_graph(self):
        """root returns None for empty graph."""
        graph = LineageGraph(session_id="test-session")
        assert graph.root is None

    def test_get_children(self):
        """Can get child nodes of a node."""
        graph = LineageGraph(session_id="test-session")

        parent = make_event(action="parent")
        child1 = make_event(action="child1", parent_event_id=parent.id)
        child2 = make_event(action="child2", parent_event_id=parent.id)
        other = make_event(action="other")

        graph.add_node(DecisionNode(event=parent, sequence_num=0))
        graph.add_node(DecisionNode(event=child1, sequence_num=1))
        graph.add_node(DecisionNode(event=child2, sequence_num=2))
        graph.add_node(DecisionNode(event=other, sequence_num=3))

        children = graph.get_children(parent.id)
        assert len(children) == 2
        assert {c.action for c in children} == {"child1", "child2"}

    def test_get_parent(self):
        """Can get parent node."""
        graph = LineageGraph(session_id="test-session")

        parent = make_event(action="parent")
        child = make_event(action="child", parent_event_id=parent.id)

        graph.add_node(DecisionNode(event=parent, sequence_num=0))
        graph.add_node(DecisionNode(event=child, sequence_num=1))

        assert graph.get_parent(child.id).action == "parent"
        assert graph.get_parent(parent.id) is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/graph/test_models.py::TestLineageGraph -v
```

Expected: FAIL with "cannot import name 'LineageGraph'"

**Step 3: Write minimal implementation**

```python
# Add to src/driftshield/core/graph/models.py

@dataclass
class LineageGraph:
    """A directed acyclic graph of decision nodes representing reasoning trajectory."""

    session_id: str
    _nodes: dict = None  # UUID -> DecisionNode

    def __post_init__(self):
        if self._nodes is None:
            self._nodes = {}

    def add_node(self, node: DecisionNode) -> None:
        """Add a node to the graph."""
        self._nodes[node.id] = node

    def get_node(self, node_id: UUID) -> DecisionNode | None:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> list[DecisionNode]:
        """Return all nodes in sequence order."""
        return sorted(self._nodes.values(), key=lambda n: n.sequence_num)

    @property
    def root(self) -> DecisionNode | None:
        """Return the root node (sequence_num 0)."""
        for node in self._nodes.values():
            if node.sequence_num == 0:
                return node
        return None

    def get_children(self, node_id: UUID) -> list[DecisionNode]:
        """Get all nodes that have this node as parent."""
        return [
            node for node in self._nodes.values()
            if node.parent_event_id == node_id
        ]

    def get_parent(self, node_id: UUID) -> DecisionNode | None:
        """Get the parent node of a given node."""
        node = self.get_node(node_id)
        if node is None or node.parent_event_id is None:
            return None
        return self.get_node(node.parent_event_id)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/graph/test_models.py::TestLineageGraph -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(graph): add LineageGraph model"
```

---

### Task 3.3: Graph Path Traversal

**Files:**
- Modify: `driftshield/src/driftshield/core/graph/models.py`
- Modify: `driftshield/tests/core/graph/test_models.py`

**Step 1: Write the failing test for path traversal**

```python
# Add to tests/core/graph/test_models.py TestLineageGraph class

    def test_path_to_root(self):
        """path_to_root returns nodes from target to root."""
        graph = LineageGraph(session_id="test-session")

        node1 = make_event(action="root")
        node2 = make_event(action="middle", parent_event_id=node1.id)
        node3 = make_event(action="leaf", parent_event_id=node2.id)

        graph.add_node(DecisionNode(event=node1, sequence_num=0))
        graph.add_node(DecisionNode(event=node2, sequence_num=1))
        graph.add_node(DecisionNode(event=node3, sequence_num=2))

        path = graph.path_to_root(node3.id)

        assert len(path) == 3
        assert [n.action for n in path] == ["leaf", "middle", "root"]

    def test_path_to_root_single_node(self):
        """path_to_root for root node returns just the root."""
        graph = LineageGraph(session_id="test-session")
        event = make_event(action="root")
        graph.add_node(DecisionNode(event=event, sequence_num=0))

        path = graph.path_to_root(event.id)

        assert len(path) == 1
        assert path[0].action == "root"

    def test_path_to_root_nonexistent_returns_empty(self):
        """path_to_root for nonexistent node returns empty list."""
        graph = LineageGraph(session_id="test-session")
        assert graph.path_to_root(uuid4()) == []

    def test_path_between(self):
        """path_between returns nodes from start to end inclusive."""
        graph = LineageGraph(session_id="test-session")

        node1 = make_event(action="n1")
        node2 = make_event(action="n2", parent_event_id=node1.id)
        node3 = make_event(action="n3", parent_event_id=node2.id)
        node4 = make_event(action="n4", parent_event_id=node3.id)

        graph.add_node(DecisionNode(event=node1, sequence_num=0))
        graph.add_node(DecisionNode(event=node2, sequence_num=1))
        graph.add_node(DecisionNode(event=node3, sequence_num=2))
        graph.add_node(DecisionNode(event=node4, sequence_num=3))

        path = graph.path_between(node2.id, node4.id)

        assert len(path) == 3
        assert [n.action for n in path] == ["n2", "n3", "n4"]

    def test_path_between_same_node(self):
        """path_between with same start and end returns single node."""
        graph = LineageGraph(session_id="test-session")
        event = make_event(action="solo")
        graph.add_node(DecisionNode(event=event, sequence_num=0))

        path = graph.path_between(event.id, event.id)

        assert len(path) == 1
        assert path[0].action == "solo"

    def test_path_between_not_connected_returns_empty(self):
        """path_between returns empty if nodes not connected."""
        graph = LineageGraph(session_id="test-session")

        node1 = make_event(action="n1")
        node2 = make_event(action="n2")  # no parent, not connected

        graph.add_node(DecisionNode(event=node1, sequence_num=0))
        graph.add_node(DecisionNode(event=node2, sequence_num=1))

        assert graph.path_between(node1.id, node2.id) == []
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/graph/test_models.py::TestLineageGraph::test_path_to_root -v
```

Expected: FAIL with "AttributeError: 'LineageGraph' object has no attribute 'path_to_root'"

**Step 3: Write minimal implementation**

```python
# Add methods to LineageGraph class in src/driftshield/core/graph/models.py

    def path_to_root(self, node_id: UUID) -> list[DecisionNode]:
        """Return path from node to root, starting with the given node."""
        path = []
        current = self.get_node(node_id)

        while current is not None:
            path.append(current)
            current = self.get_parent(current.id)

        return path

    def path_between(self, start_id: UUID, end_id: UUID) -> list[DecisionNode]:
        """Return path from start to end, inclusive. Empty if not connected."""
        if start_id == end_id:
            node = self.get_node(start_id)
            return [node] if node else []

        # Walk backward from end to find start
        path_to_root = self.path_to_root(end_id)

        try:
            start_idx = next(
                i for i, node in enumerate(path_to_root)
                if node.id == start_id
            )
            # Reverse to get start -> end order
            return list(reversed(path_to_root[: start_idx + 1]))
        except StopIteration:
            return []
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/graph/test_models.py::TestLineageGraph -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(graph): add path traversal methods"
```

---

## Phase 4: Graph Builder

### Task 4.1: Build Graph from Events

**Files:**
- Create: `driftshield/src/driftshield/core/graph/builder.py`
- Create: `driftshield/tests/core/graph/test_builder.py`

**Step 1: Write the failing test for GraphBuilder**

```python
# tests/core/graph/test_builder.py
"""Tests for graph builder."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType
from driftshield.core.graph.builder import build_graph


def make_event(**kwargs) -> CanonicalEvent:
    """Factory for creating test events."""
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestBuildGraph:
    def test_build_empty_graph(self):
        """Building from empty list returns empty graph."""
        graph = build_graph([], session_id="test")
        assert len(graph.nodes) == 0
        assert graph.session_id == "test"

    def test_build_single_node_graph(self):
        """Building from single event creates single-node graph."""
        event = make_event(session_id="s1", action="solo")
        graph = build_graph([event], session_id="s1")

        assert len(graph.nodes) == 1
        assert graph.root.action == "solo"
        assert graph.root.sequence_num == 0

    def test_build_linear_chain(self):
        """Building from chain of events preserves parent relationships."""
        event1 = make_event(session_id="s1", action="first")
        event2 = make_event(session_id="s1", action="second", parent_event_id=event1.id)
        event3 = make_event(session_id="s1", action="third", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="s1")

        assert len(graph.nodes) == 3
        assert graph.root.action == "first"

        path = graph.path_to_root(event3.id)
        assert [n.action for n in path] == ["third", "second", "first"]

    def test_build_assigns_sequence_numbers_by_timestamp(self):
        """Sequence numbers are assigned based on timestamp order."""
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 1, 1, 10, 0, 2, tzinfo=timezone.utc)

        # Create out of order
        event2 = make_event(session_id="s1", action="second", timestamp=t2)
        event1 = make_event(session_id="s1", action="first", timestamp=t1)
        event3 = make_event(session_id="s1", action="third", timestamp=t3)

        graph = build_graph([event2, event1, event3], session_id="s1")

        nodes = graph.nodes  # should be in sequence order
        assert [n.action for n in nodes] == ["first", "second", "third"]
        assert [n.sequence_num for n in nodes] == [0, 1, 2]

    def test_build_with_branching(self):
        """Graph can have nodes with multiple children."""
        root = make_event(session_id="s1", action="root")
        child1 = make_event(session_id="s1", action="child1", parent_event_id=root.id)
        child2 = make_event(session_id="s1", action="child2", parent_event_id=root.id)

        graph = build_graph([root, child1, child2], session_id="s1")

        children = graph.get_children(root.id)
        assert len(children) == 2
        assert {c.action for c in children} == {"child1", "child2"}
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/core/graph/test_builder.py -v
```

Expected: FAIL with "cannot import name 'build_graph'"

**Step 3: Write minimal implementation**

```python
# src/driftshield/core/graph/builder.py
"""Build lineage graphs from canonical events."""

from driftshield.core.models import CanonicalEvent
from driftshield.core.graph.models import DecisionNode, LineageGraph


def build_graph(events: list[CanonicalEvent], session_id: str) -> LineageGraph:
    """
    Build a LineageGraph from a list of CanonicalEvents.

    Events are sorted by timestamp and assigned sequence numbers.
    """
    graph = LineageGraph(session_id=session_id)

    # Sort events by timestamp
    sorted_events = sorted(events, key=lambda e: e.timestamp)

    # Create nodes with sequence numbers
    for seq_num, event in enumerate(sorted_events):
        node = DecisionNode(event=event, sequence_num=seq_num)
        graph.add_node(node)

    return graph
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/core/graph/test_builder.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add driftshield/
git commit -m "feat(graph): add graph builder"
```

---

## Phase 5: Synthetic Validation Scenarios

### Task 5.1: Create Test Fixtures Module

**Files:**
- Create: `driftshield/tests/fixtures/__init__.py`
- Create: `driftshield/tests/fixtures/scenarios.py`

**Step 1: Create fixtures package**

```bash
mkdir -p driftshield/tests/fixtures
touch driftshield/tests/fixtures/__init__.py
```

**Step 2: Write scenario factory**

```python
# tests/fixtures/scenarios.py
"""Synthetic validation scenarios for testing DriftShield analysis."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import LineageGraph


def _ts(minutes: int) -> datetime:
    """Create timestamp offset from a base time."""
    base = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes)


def coverage_gap_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Agent reviews complex document, misses material exception.

    Contract review agent processes indemnification clause with 4 subsections.
    Subsection (c) contains "except where" carve-out.
    Agent summarizes as "standard structure" without referencing (c).

    Expected inflection: Node 4 (review_indemnity)
    Expected flags: coverage_gap, assumption_mutation
    """
    session_id = "coverage-gap-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="receive_document",
            inputs={"document_type": "MSA", "vendor": "DataFlow Inc"},
            outputs={"status": "received", "pages": 24},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="extract_clauses",
            parent_event_id=node1_id,
            inputs={"document_id": str(node1_id)},
            outputs={
                "clauses": {
                    "liability_cap": "12 months of fees",
                    "termination": "90 days notice",
                    "data_handling": "Processor role",
                    "indemnification": {
                        "full_text": "Supplier shall indemnify...(a)...(b)...(c) except where claim arises from Customer-provided data...(d)...",
                        "subsections": ["a", "b", "c", "d"],
                        "token_count": 847,
                    },
                }
            },
        )
    )
    node2_id = events[1].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.BRANCH,
            agent_id="doc-reviewer",
            action="review_liability",
            parent_event_id=node2_id,
            inputs={"clause": "liability_cap", "text": "12 months of fees"},
            outputs={"assessment": "Adequate for SaaS", "flag": False},
        )
    )
    node3_id = events[2].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.BRANCH,
            agent_id="doc-reviewer",
            action="review_indemnity",
            parent_event_id=node3_id,
            inputs={
                "clause": "indemnification",
                "full_text": "Supplier shall indemnify...(a)...(b)...(c) except where claim arises from Customer-provided data...(d)...",
                "subsections": ["a", "b", "c", "d"],
            },
            outputs={
                "assessment": "Standard indemnification structure",
                "referenced_subsections": ["a", "b", "d"],  # Missing (c)!
                "flag": False,
            },
            # This should be detected by analysis
            risk_classification=RiskClassification(
                coverage_gap=True,
                assumption_mutation=True,
            ),
        )
    )
    node4_id = events[3].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(4),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="generate_summary",
            parent_event_id=node4_id,
            inputs={"assessments": ["liability", "termination", "data", "indemnity"]},
            outputs={"summary": "No material risks identified"},
        )
    )
    node5_id = events[4].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(5),
            event_type=EventType.OUTPUT,
            agent_id="doc-reviewer",
            action="output",
            parent_event_id=node5_id,
            inputs={},
            outputs={
                "recommendation": "Proceed to signature",
                "flags": [],
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "coverage_gap",
        "description": "Agent misses material exception in complex clause",
        "expected_inflection_node_action": "review_indemnity",
        "expected_inflection_node_id": node4_id,
        "expected_risk_flags": ["coverage_gap", "assumption_mutation"],
        "failure_mode": "coverage_gap",
    }

    return graph, metadata


def assumption_introduction_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Agent makes inference not supported by inputs.

    Research agent retrieves sector data showing 4pt margin decline.
    Client data shows 6pt decline.
    Agent concludes "industry trend explains client decline" without
    computing relative underperformance.

    Expected inflection: Node 4 (reasoning_step)
    Expected flags: assumption_mutation
    """
    session_id = "assumption-intro-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="receive_application",
            inputs={"applicant": "MidWest Manufacturing", "request": "$2M credit line"},
            outputs={"status": "received"},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="fetch_financials",
            parent_event_id=node1_id,
            inputs={"company": "MidWest Manufacturing"},
            outputs={
                "revenue_trend": [12_000_000, 14_000_000, 11_000_000],
                "margin_trend": [0.18, 0.16, 0.12],  # 6pt decline
                "debt_ebitda": 2.9,
            },
        )
    )
    node2_id = events[1].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="fetch_industry_data",
            parent_event_id=node2_id,
            inputs={"sector": "manufacturing"},
            outputs={
                "sector_outlook": "Headwinds from supply chain normalization",
                "avg_margin_decline": 0.04,  # 4pt decline
            },
        )
    )
    node3_id = events[2].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.BRANCH,
            agent_id="underwriting-agent",
            action="reasoning_step",
            parent_event_id=node3_id,
            inputs={
                "client_margin_decline": 0.06,
                "sector_margin_decline": 0.04,
            },
            outputs={
                "reasoning": "Margin decline is industry-wide trend",
                "relative_comparison": None,  # Should have computed this!
            },
            risk_classification=RiskClassification(assumption_mutation=True),
        )
    )
    node4_id = events[3].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(4),
            event_type=EventType.OUTPUT,
            agent_id="underwriting-agent",
            action="output",
            parent_event_id=node4_id,
            inputs={},
            outputs={
                "recommendation": "APPROVE",
                "risk_rating": "Standard",
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "assumption_introduction",
        "description": "Agent uses sector data to excuse rather than benchmark client performance",
        "expected_inflection_node_action": "reasoning_step",
        "expected_inflection_node_id": node4_id,
        "expected_risk_flags": ["assumption_mutation"],
        "failure_mode": "assumption_mutation",
    }

    return graph, metadata


def cross_tool_contamination_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Output from Tool A incorrectly influences Tool B usage.

    Agent fetches customer data, then fetches pricing data.
    Customer metadata (discount tier) incorrectly applied to
    a different product's pricing calculation.

    Expected inflection: Node 3 (apply_pricing)
    Expected flags: context_contamination
    """
    session_id = "contamination-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="receive_order",
            inputs={"customer_id": "C123", "product_id": "P456"},
            outputs={"status": "received"},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="fetch_customer",
            parent_event_id=node1_id,
            inputs={"customer_id": "C123"},
            outputs={
                "customer_name": "Acme Corp",
                "discount_tier": "gold",  # For product category A
                "discount_category": "A",
            },
        )
    )
    node2_id = events[1].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="apply_pricing",
            parent_event_id=node2_id,
            inputs={
                "product_id": "P456",
                "product_category": "B",  # Different category!
                "customer_discount_tier": "gold",  # From category A
            },
            outputs={
                "base_price": 100,
                "discount_applied": 0.20,  # Wrong! Gold tier doesn't apply to category B
                "final_price": 80,
            },
            risk_classification=RiskClassification(context_contamination=True),
        )
    )
    node3_id = events[2].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.OUTPUT,
            agent_id="order-agent",
            action="output",
            parent_event_id=node3_id,
            inputs={},
            outputs={
                "order_total": 80,
                "status": "created",
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "cross_tool_contamination",
        "description": "Discount from one category incorrectly applied to different category",
        "expected_inflection_node_action": "apply_pricing",
        "expected_inflection_node_id": node3_id,
        "expected_risk_flags": ["context_contamination"],
        "failure_mode": "context_contamination",
    }

    return graph, metadata


ALL_SCENARIOS = [
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
]
```

**Step 3: Commit**

```bash
git add driftshield/
git commit -m "test: add synthetic validation scenarios"
```

---

### Task 5.2: Scenario Validation Tests

**Files:**
- Create: `driftshield/tests/test_scenarios.py`

**Step 1: Write scenario validation tests**

```python
# tests/test_scenarios.py
"""Validate synthetic scenarios have expected structure."""

import pytest

from tests.fixtures.scenarios import (
    ALL_SCENARIOS,
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
)


class TestScenarioStructure:
    """Verify all scenarios have correct structure for testing."""

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_returns_graph_and_metadata(self, scenario_fn):
        """Each scenario returns (graph, metadata) tuple."""
        result = scenario_fn()
        assert isinstance(result, tuple)
        assert len(result) == 2

        graph, metadata = result
        assert graph is not None
        assert isinstance(metadata, dict)

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_metadata_has_required_keys(self, scenario_fn):
        """Each scenario metadata has required keys."""
        _, metadata = scenario_fn()

        required_keys = [
            "name",
            "description",
            "expected_inflection_node_action",
            "expected_inflection_node_id",
            "expected_risk_flags",
            "failure_mode",
        ]
        for key in required_keys:
            assert key in metadata, f"Missing key: {key}"

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_graph_has_nodes(self, scenario_fn):
        """Each scenario graph has at least 2 nodes."""
        graph, _ = scenario_fn()
        assert len(graph.nodes) >= 2

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_inflection_node_exists(self, scenario_fn):
        """Expected inflection node exists in graph."""
        graph, metadata = scenario_fn()
        inflection_id = metadata["expected_inflection_node_id"]
        node = graph.get_node(inflection_id)

        assert node is not None
        assert node.action == metadata["expected_inflection_node_action"]

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_inflection_node_has_risk_flags(self, scenario_fn):
        """Expected inflection node has risk flags set."""
        graph, metadata = scenario_fn()
        inflection_id = metadata["expected_inflection_node_id"]
        node = graph.get_node(inflection_id)

        assert node.has_risk_flags()

        # Check expected flags are set
        risk = node.event.risk_classification
        for flag in metadata["expected_risk_flags"]:
            assert getattr(risk, flag) is True, f"Expected flag {flag} to be True"


class TestCoverageGapScenario:
    """Specific tests for coverage gap scenario."""

    def test_has_four_subsections_in_input(self):
        """Inflection node input has 4 subsections."""
        graph, metadata = coverage_gap_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert "subsections" in node.inputs
        assert len(node.inputs["subsections"]) == 4

    def test_output_missing_subsection_c(self):
        """Inflection node output only references 3 subsections."""
        graph, metadata = coverage_gap_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        referenced = node.outputs.get("referenced_subsections", [])
        assert "c" not in referenced
        assert len(referenced) == 3


class TestAssumptionIntroductionScenario:
    """Specific tests for assumption introduction scenario."""

    def test_has_both_decline_values(self):
        """Inflection node has both client and sector decline in inputs."""
        graph, metadata = assumption_introduction_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert "client_margin_decline" in node.inputs
        assert "sector_margin_decline" in node.inputs
        assert node.inputs["client_margin_decline"] > node.inputs["sector_margin_decline"]

    def test_no_relative_comparison_computed(self):
        """Agent didn't compute relative comparison."""
        graph, metadata = assumption_introduction_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert node.outputs.get("relative_comparison") is None


class TestCrossToolContaminationScenario:
    """Specific tests for cross-tool contamination scenario."""

    def test_discount_category_mismatch(self):
        """Discount from category A applied to category B product."""
        graph, metadata = cross_tool_contamination_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        # Product is category B but discount is from category A context
        assert node.inputs["product_category"] == "B"
        assert node.inputs["customer_discount_tier"] == "gold"
```

**Step 2: Run tests**

```bash
pytest tests/test_scenarios.py -v
```

Expected: PASS

**Step 3: Commit**

```bash
git add driftshield/
git commit -m "test: add scenario validation tests"
```

---

## Phase 6: Inflection Node Detection

### Task 6.1: Find Inflection Node

**Files:**
- Create: `driftshield/src/driftshield/core/analysis/__init__.py`
- Create: `driftshield/src/driftshield/core/analysis/inflection.py`
- Create: `driftshield/tests/core/analysis/__init__.py`
- Create: `driftshield/tests/core/analysis/test_inflection.py`

**Step 1: Create analysis package**

```bash
mkdir -p driftshield/src/driftshield/core/analysis
mkdir -p driftshield/tests/core/analysis
touch driftshield/src/driftshield/core/analysis/__init__.py
touch driftshield/tests/core/analysis/__init__.py
```

**Step 2: Write the failing test**

```python
# tests/core/analysis/test_inflection.py
"""Tests for inflection node detection."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.analysis.inflection import find_inflection_node
from tests.fixtures.scenarios import (
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
)


def make_event(**kwargs) -> CanonicalEvent:
    """Factory for creating test events."""
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestFindInflectionNode:
    def test_returns_none_for_empty_graph(self):
        """Empty graph has no inflection node."""
        graph = build_graph([], session_id="test")
        result = find_inflection_node(graph, uuid4())
        assert result is None

    def test_returns_none_for_nonexistent_failure_node(self):
        """Nonexistent failure node returns None."""
        event = make_event()
        graph = build_graph([event], session_id="test")
        result = find_inflection_node(graph, uuid4())
        assert result is None

    def test_returns_none_when_no_risk_flags(self):
        """Graph with no risk flags has no inflection."""
        event1 = make_event(action="first")
        event2 = make_event(action="second", parent_event_id=event1.id)

        graph = build_graph([event1, event2], session_id="test")
        result = find_inflection_node(graph, event2.id)

        assert result is None

    def test_finds_single_risky_node(self):
        """Single node with risk flags is the inflection."""
        event1 = make_event(action="clean")
        event2 = make_event(
            action="risky",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        event3 = make_event(action="failure", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="test")
        result = find_inflection_node(graph, event3.id)

        assert result is not None
        assert result.action == "risky"

    def test_finds_first_risky_node_walking_backward(self):
        """When multiple risky nodes, finds first (closest to failure)."""
        event1 = make_event(
            action="early_risk",
            risk_classification=RiskClassification(policy_divergence=True),
        )
        event2 = make_event(
            action="later_risk",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        event3 = make_event(action="failure", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="test")
        result = find_inflection_node(graph, event3.id)

        # Walking backward from failure, we hit later_risk first
        assert result.action == "later_risk"

    def test_failure_node_itself_can_be_inflection(self):
        """If failure node has risk flags, it is the inflection."""
        event1 = make_event(action="clean")
        event2 = make_event(
            action="failure_with_risk",
            parent_event_id=event1.id,
            risk_classification=RiskClassification(coverage_gap=True),
        )

        graph = build_graph([event1, event2], session_id="test")
        result = find_inflection_node(graph, event2.id)

        assert result.action == "failure_with_risk"


class TestInflectionWithScenarios:
    """Test inflection detection with synthetic scenarios."""

    def test_coverage_gap_scenario(self):
        """Finds correct inflection in coverage gap scenario."""
        graph, metadata = coverage_gap_scenario()

        # Find the last node (output) as failure point
        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]
        assert result.action == metadata["expected_inflection_node_action"]

    def test_assumption_introduction_scenario(self):
        """Finds correct inflection in assumption introduction scenario."""
        graph, metadata = assumption_introduction_scenario()

        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]

    def test_cross_tool_contamination_scenario(self):
        """Finds correct inflection in cross-tool contamination scenario."""
        graph, metadata = cross_tool_contamination_scenario()

        failure_node = graph.nodes[-1]
        result = find_inflection_node(graph, failure_node.id)

        assert result is not None
        assert result.id == metadata["expected_inflection_node_id"]
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/core/analysis/test_inflection.py -v
```

Expected: FAIL with "cannot import name 'find_inflection_node'"

**Step 4: Write minimal implementation**

```python
# src/driftshield/core/analysis/inflection.py
"""Inflection node detection."""

from uuid import UUID

from driftshield.core.graph.models import DecisionNode, LineageGraph


def find_inflection_node(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> DecisionNode | None:
    """
    Find the inflection node by walking backward from failure.

    The inflection node is the first node with risk flags set,
    walking backward from the failure node toward the root.

    Args:
        graph: The lineage graph to search
        failure_node_id: ID of the node where failure was observed

    Returns:
        The inflection node, or None if no risky node found
    """
    path = graph.path_to_root(failure_node_id)

    if not path:
        return None

    for node in path:
        if node.has_risk_flags():
            return node

    return None
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/core/analysis/test_inflection.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add driftshield/
git commit -m "feat(analysis): add inflection node detection"
```

---

## Phase 7: Continue with remaining tasks...

The implementation plan continues with:

- **Phase 7**: Risk Classification Heuristics
- **Phase 8**: Parser Interface and JSON Parser
- **Phase 9**: Database Models (SQLAlchemy)
- **Phase 10**: API Routes (FastAPI)
- **Phase 11**: Report Generation
- **Phase 12**: React UI Foundation
- **Phase 13**: Investigation View Components
- **Phase 14**: Docker Deployment

---

## Summary

This implementation plan covers the core foundation needed to prove the DriftShield thesis:

1. **Core domain models** — CanonicalEvent, Session, RiskClassification
2. **Graph models** — DecisionNode, LineageGraph with path traversal
3. **Graph builder** — Construct graphs from events
4. **Synthetic scenarios** — Validation cases for coverage gap, assumption mutation, contamination
5. **Inflection detection** — Find where reasoning diverged

Each task follows TDD: write failing test, implement, verify, commit.

---

**Plan complete and saved to `docs/plans/2025-02-13-driftshield-v1-implementation.md`.**

**Two execution options:**

1. **Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** — Open new session in worktree with executing-plans, batch execution with checkpoints

**Which approach?**
