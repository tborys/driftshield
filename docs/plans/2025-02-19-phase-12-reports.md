# Phase 12: Report Generation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a template based report generation system producing Markdown and JSON forensic analysis reports from AnalysisResult data.

**Architecture:** ReportBuilder assembles structured ReportData from AnalysisResult. Separate renderers for Markdown (Jinja2) and JSON. Templates shipped as package data. Integrated with both API and CLI.

**Tech Stack:** Jinja2, Python dataclasses

**Design doc:** `docs/plans/2025-02-19-phases-10-14-design.md` (Phase 12 section)

**Prerequisite:** Phase 10 complete. Phase 11 has stub report endpoints ready to be wired up.

---

## Task 12.1: Report Data Models

**Files:**
- Create: `src/driftshield/reports/__init__.py`
- Create: `src/driftshield/reports/models.py`
- Create: `tests/reports/__init__.py`
- Create: `tests/reports/test_models.py`

**Step 1: Write the failing test**

```python
# tests/reports/test_models.py
import uuid
from datetime import datetime, timezone

from driftshield.reports.models import (
    ReportData, ReportSection, NodeRow, RiskTransition, ReportType,
)


def test_create_report_data():
    report = ReportData(
        session_id=uuid.uuid4(),
        agent_id="test-agent",
        generated_at=datetime.now(timezone.utc),
        report_type=ReportType.FULL,
        sections=[],
    )
    assert report.report_type == ReportType.FULL
    assert report.sections == []


def test_report_section():
    section = ReportSection(
        title="Behavioural Lineage Reconstruction",
        content="Analysis of decision flow.",
        node_table=[
            NodeRow(
                sequence=1,
                node_id=uuid.uuid4(),
                event_type="TOOL_CALL",
                action="read_file",
                risk_flags=["coverage_gap"],
                is_inflection=False,
            ),
        ],
    )
    assert len(section.node_table) == 1
    assert section.node_table[0].risk_flags == ["coverage_gap"]


def test_risk_transition():
    t = RiskTransition(
        from_node_id=uuid.uuid4(),
        to_node_id=uuid.uuid4(),
        risk_type="coverage_gap",
        description="Gap introduced at read_file, propagated to respond",
    )
    assert t.risk_type == "coverage_gap"


def test_report_type_enum():
    assert ReportType.FULL.value == "full"
    assert ReportType.SUMMARY.value == "summary"
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_models.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# src/driftshield/reports/__init__.py
```

```python
# src/driftshield/reports/models.py
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReportType(Enum):
    FULL = "full"
    SUMMARY = "summary"


@dataclass
class NodeRow:
    sequence: int
    node_id: uuid.UUID
    event_type: str
    action: str | None
    risk_flags: list[str] = field(default_factory=list)
    is_inflection: bool = False


@dataclass
class RiskTransition:
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    risk_type: str
    description: str


@dataclass
class ReportSection:
    title: str
    content: str = ""
    node_table: list[NodeRow] = field(default_factory=list)
    risk_transitions: list[RiskTransition] = field(default_factory=list)


@dataclass
class ReportData:
    session_id: uuid.UUID
    agent_id: str
    generated_at: datetime
    report_type: ReportType
    sections: list[ReportSection]
    inflection_node_id: uuid.UUID | None = None
    inflection_action: str | None = None
    total_events: int = 0
    flagged_events: int = 0
    classification: str = "isolated"
    recurrence_probability: str = "unknown"
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_models.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/driftshield/reports/ tests/reports/
git commit -m "feat(reports): add report data models"
```

---

## Task 12.2: ReportBuilder — Assemble ReportData from AnalysisResult

**Files:**
- Create: `src/driftshield/reports/builder.py`
- Create: `tests/reports/test_builder.py`

**Step 1: Write the failing test**

```python
# tests/reports/test_builder.py
import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, RiskClassification, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.models import ReportType


@pytest.fixture
def sample_result():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="read_file",
            inputs={"items": ["a", "b", "c"]},
            outputs={"summary": "Covers a and b"},
        ),
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.OUTPUT, agent_id="test", action="respond",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    return result, session


def test_build_full_report(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.FULL)

    assert report_data.session_id == session.id
    assert report_data.agent_id == "test"
    assert report_data.report_type == ReportType.FULL
    assert len(report_data.sections) == 5
    assert report_data.sections[0].title == "Behavioural Lineage Reconstruction"
    assert report_data.sections[1].title == "Inflection Node Identification"
    assert report_data.sections[2].title == "Risk State Transition Mapping"
    assert report_data.sections[3].title == "Systemic Exposure Assessment"
    assert report_data.sections[4].title == "Recurrence Risk Analysis"


def test_build_summary_report(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.SUMMARY)

    assert report_data.report_type == ReportType.SUMMARY
    assert len(report_data.sections) == 2


def test_lineage_section_has_node_table(sample_result):
    result, session = sample_result
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=ReportType.FULL)

    lineage = report_data.sections[0]
    assert len(lineage.node_table) == len(result.graph.nodes)
    for row in lineage.node_table:
        assert row.event_type in ["TOOL_CALL", "OUTPUT", "BRANCH", "ASSUMPTION", "CONSTRAINT_CHECK", "HANDOFF"]
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_builder.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# src/driftshield/reports/builder.py
from datetime import datetime, timezone

from driftshield.core.models import Session as DomainSession
from driftshield.core.analysis.session import AnalysisResult
from driftshield.reports.models import (
    ReportData, ReportSection, ReportType, NodeRow, RiskTransition,
)


class ReportBuilder:
    def build(
        self,
        session: DomainSession,
        result: AnalysisResult,
        report_type: ReportType = ReportType.FULL,
    ) -> ReportData:
        sections = [
            self._build_lineage_section(result),
            self._build_inflection_section(result),
        ]
        if report_type == ReportType.FULL:
            sections.extend([
                self._build_risk_transition_section(result),
                self._build_exposure_section(result),
                self._build_recurrence_section(result),
            ])

        return ReportData(
            session_id=session.id,
            agent_id=session.agent_id,
            generated_at=datetime.now(timezone.utc),
            report_type=report_type,
            sections=sections,
            inflection_node_id=(
                result.inflection_node.id if result.inflection_node else None
            ),
            inflection_action=(
                result.inflection_node.action if result.inflection_node else None
            ),
            total_events=result.total_events,
            flagged_events=result.flagged_events,
        )

    def _build_lineage_section(self, result: AnalysisResult) -> ReportSection:
        rows = []
        for node in result.graph.nodes:
            risk_flags = []
            rc = node.event.risk_classification
            if rc:
                risk_flags = rc.active_flags()
            rows.append(NodeRow(
                sequence=node.sequence_num,
                node_id=node.id,
                event_type=node.event_type.value,
                action=node.action,
                risk_flags=risk_flags,
                is_inflection=(
                    result.inflection_node is not None
                    and node.id == result.inflection_node.id
                ),
            ))
        return ReportSection(
            title="Behavioural Lineage Reconstruction",
            content="Chronological reconstruction of the agent's decision path.",
            node_table=rows,
        )

    def _build_inflection_section(self, result: AnalysisResult) -> ReportSection:
        if result.inflection_node:
            content = (
                f"Inflection detected at node #{result.inflection_node.sequence_num} "
                f"({result.inflection_node.action}). "
                f"This is where the agent's reasoning first diverged from expected behaviour."
            )
        else:
            content = "No inflection node detected. The decision path appears consistent."
        return ReportSection(
            title="Inflection Node Identification",
            content=content,
        )

    def _build_risk_transition_section(self, result: AnalysisResult) -> ReportSection:
        transitions = []
        nodes = result.graph.nodes
        for i, node in enumerate(nodes):
            rc = node.event.risk_classification
            if rc and rc.has_any_flag():
                for flag in rc.active_flags():
                    # Find next node if exists
                    if i + 1 < len(nodes):
                        transitions.append(RiskTransition(
                            from_node_id=node.id,
                            to_node_id=nodes[i + 1].id,
                            risk_type=flag,
                            description=f"{flag} introduced at {node.action}",
                        ))
        return ReportSection(
            title="Risk State Transition Mapping",
            content="How risk propagated through the decision graph.",
            risk_transitions=transitions,
        )

    def _build_exposure_section(self, result: AnalysisResult) -> ReportSection:
        if result.flagged_events == 0:
            classification = "No risk flags detected."
        elif result.flagged_events == 1:
            classification = "Isolated: single point of risk in the decision path."
        else:
            classification = f"Multiple risk points ({result.flagged_events} flagged events)."
        return ReportSection(
            title="Systemic Exposure Assessment",
            content=classification,
        )

    def _build_recurrence_section(self, result: AnalysisResult) -> ReportSection:
        return ReportSection(
            title="Recurrence Risk Analysis",
            content=(
                "Recurrence analysis requires multiple sessions. "
                "Insufficient data for recurrence assessment in single session analysis."
            ),
        )
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_builder.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/driftshield/reports/builder.py tests/reports/test_builder.py
git commit -m "feat(reports): add ReportBuilder to assemble ReportData from AnalysisResult"
```

---

## Task 12.3: Markdown Renderer with Jinja2

**Files:**
- Create: `src/driftshield/reports/markdown.py`
- Create: `src/driftshield/reports/templates/full.md.j2`
- Create: `src/driftshield/reports/templates/summary.md.j2`
- Create: `tests/reports/test_markdown.py`

**Step 1: Write the failing test**

```python
# tests/reports/test_markdown.py
import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.markdown import render_markdown
from driftshield.reports.models import ReportType


@pytest.fixture
def full_report_data():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="read_file",
            inputs={"items": ["a", "b", "c"]},
            outputs={"summary": "Covers a and b"},
        ),
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.OUTPUT, agent_id="test", action="respond",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test-agent", started_at=now, status=SessionStatus.COMPLETED,
    )
    builder = ReportBuilder()
    return builder.build(session, result, report_type=ReportType.FULL)


def test_render_full_report_markdown(full_report_data):
    md = render_markdown(full_report_data)
    assert "# Forensic Analysis Report" in md
    assert "test-agent" in md
    assert "Behavioural Lineage Reconstruction" in md
    assert "Inflection Node Identification" in md
    assert "Risk State Transition Mapping" in md
    assert "Systemic Exposure Assessment" in md
    assert "Recurrence Risk Analysis" in md


def test_render_has_node_table(full_report_data):
    md = render_markdown(full_report_data)
    assert "TOOL_CALL" in md
    assert "read_file" in md


def test_render_summary_report():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="start",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    builder = ReportBuilder()
    data = builder.build(session, result, report_type=ReportType.SUMMARY)
    md = render_markdown(data)
    assert "# Forensic Analysis Report" in md
    assert "Behavioural Lineage Reconstruction" in md
    # Summary should NOT have sections 3-5
    assert "Risk State Transition Mapping" not in md
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_markdown.py -v`
Expected: FAIL with ImportError

**Step 3: Write Jinja2 templates**

```jinja2
{# src/driftshield/reports/templates/full.md.j2 #}
# Forensic Analysis Report

**Session:** {{ report.session_id }}
**Agent:** {{ report.agent_id }}
**Generated:** {{ report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}
**Events:** {{ report.total_events }} total, {{ report.flagged_events }} flagged

---
{% for section in report.sections %}

## {{ loop.index }}. {{ section.title }}

{{ section.content }}
{% if section.node_table %}

| # | Node | Type | Action | Risk Flags |
|---|------|------|--------|------------|
{% for row in section.node_table %}
| {{ row.sequence }} | {{ row.node_id | string | truncate(8, False, '') }} | {{ row.event_type }} | {{ row.action or '—' }} | {{ row.risk_flags | join(', ') if row.risk_flags else '—' }} |
{% endfor %}
{% endif %}
{% if section.risk_transitions %}
{% for t in section.risk_transitions %}
- **{{ t.from_node_id | string | truncate(8, False, '') }}** → **{{ t.to_node_id | string | truncate(8, False, '') }}**: {{ t.description }}
{% endfor %}
{% endif %}
{% endfor %}
```

```jinja2
{# src/driftshield/reports/templates/summary.md.j2 #}
# Forensic Analysis Report (Summary)

**Session:** {{ report.session_id }}
**Agent:** {{ report.agent_id }}
**Generated:** {{ report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}

---
{% for section in report.sections %}

## {{ loop.index }}. {{ section.title }}

{{ section.content }}
{% if section.node_table %}

| # | Node | Type | Action | Risk Flags |
|---|------|------|--------|------------|
{% for row in section.node_table %}
| {{ row.sequence }} | {{ row.node_id | string | truncate(8, False, '') }} | {{ row.event_type }} | {{ row.action or '—' }} | {{ row.risk_flags | join(', ') if row.risk_flags else '—' }} |
{% endfor %}
{% endif %}
{% endfor %}
```

**Step 4: Write renderer**

```python
# src/driftshield/reports/markdown.py
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from driftshield.reports.models import ReportData, ReportType

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_markdown(report: ReportData) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template_name = {
        ReportType.FULL: "full.md.j2",
        ReportType.SUMMARY: "summary.md.j2",
    }.get(report.report_type, "full.md.j2")

    template = env.get_template(template_name)
    return template.render(report=report)
```

**Step 5: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_markdown.py -v`
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add src/driftshield/reports/ tests/reports/test_markdown.py
git commit -m "feat(reports): add Jinja2 Markdown renderer with full and summary templates"
```

---

## Task 12.4: JSON Export

**Files:**
- Create: `src/driftshield/reports/json_export.py`
- Create: `tests/reports/test_json_export.py`

**Step 1: Write the failing test**

```python
# tests/reports/test_json_export.py
import json
import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.models import (
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.json_export import export_json
from driftshield.reports.models import ReportType


@pytest.fixture
def report_data():
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    events = [
        CanonicalEvent(
            id=uuid.uuid4(), session_id=session_id, timestamp=now,
            event_type=EventType.TOOL_CALL, agent_id="test", action="read_file",
        ),
    ]
    result = analyze_session(events)
    session = DomainSession(
        id=session_id, agent_id="test", started_at=now, status=SessionStatus.COMPLETED,
    )
    return ReportBuilder().build(session, result, report_type=ReportType.FULL)


def test_export_json_returns_dict(report_data):
    data = export_json(report_data)
    assert isinstance(data, dict)
    assert "session_id" in data
    assert "sections" in data
    assert len(data["sections"]) == 5


def test_export_json_is_serialisable(report_data):
    data = export_json(report_data)
    serialised = json.dumps(data)
    assert isinstance(serialised, str)
    parsed = json.loads(serialised)
    assert parsed["agent_id"] == "test"


def test_export_json_section_structure(report_data):
    data = export_json(report_data)
    section = data["sections"][0]
    assert "title" in section
    assert "content" in section
    assert "node_table" in section
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_json_export.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# src/driftshield/reports/json_export.py
from typing import Any

from driftshield.reports.models import ReportData


def export_json(report: ReportData) -> dict[str, Any]:
    return {
        "session_id": str(report.session_id),
        "agent_id": report.agent_id,
        "generated_at": report.generated_at.isoformat(),
        "report_type": report.report_type.value,
        "total_events": report.total_events,
        "flagged_events": report.flagged_events,
        "inflection_node_id": str(report.inflection_node_id) if report.inflection_node_id else None,
        "inflection_action": report.inflection_action,
        "classification": report.classification,
        "recurrence_probability": report.recurrence_probability,
        "sections": [
            {
                "title": s.title,
                "content": s.content,
                "node_table": [
                    {
                        "sequence": row.sequence,
                        "node_id": str(row.node_id),
                        "event_type": row.event_type,
                        "action": row.action,
                        "risk_flags": row.risk_flags,
                        "is_inflection": row.is_inflection,
                    }
                    for row in s.node_table
                ],
                "risk_transitions": [
                    {
                        "from_node_id": str(t.from_node_id),
                        "to_node_id": str(t.to_node_id),
                        "risk_type": t.risk_type,
                        "description": t.description,
                    }
                    for t in s.risk_transitions
                ],
            }
            for s in report.sections
        ],
    }
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/reports/test_json_export.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/driftshield/reports/json_export.py tests/reports/test_json_export.py
git commit -m "feat(reports): add JSON export for structured report output"
```

---

## Task 12.5: Wire Report Generation into API Endpoint

**Files:**
- Modify: `src/driftshield/api/routes/reports.py`
- Modify: `tests/api/test_reports.py`

**Step 1: Update the API report generation test**

Add to `tests/api/test_reports.py`:

```python
def test_generated_report_has_real_content(client, auth_headers, seeded_session, db_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )
    assert response.status_code == 201
    report_id = response.json()["id"]

    # Fetch the report and check it has real content
    get_response = client.get(f"/api/reports/{report_id}", headers=auth_headers)
    data = get_response.json()
    assert "Forensic Analysis Report" in data["content_markdown"]
    assert data["content_json"]["sections"] is not None
    assert len(data["content_json"]["sections"]) == 5
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/api/test_reports.py::test_generated_report_has_real_content -v`
Expected: FAIL (stub content doesn't have sections)

**Step 3: Update report endpoint to use ReportBuilder**

Replace the stub generation in `src/driftshield/api/routes/reports.py` `generate_report` function:

```python
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.core.analysis.session import AnalysisResult
from driftshield.db.persistence import PersistenceService
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.markdown import render_markdown
from driftshield.reports.json_export import export_json
from driftshield.reports.models import ReportType


@router.post("/api/sessions/{session_id}/report", status_code=201)
def generate_report(
    session_id: uuid.UUID,
    request: GenerateReportRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    session_model = db.get(SessionModel, session_id)
    if session_model is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = PersistenceService(db)
    domain_session = service.load_session(session_id)
    graph = service.load_graph(session_id)

    if graph is None:
        raise HTTPException(status_code=404, detail="No graph data for session")

    # Reconstruct a minimal AnalysisResult from stored data
    from driftshield.core.analysis.inflection import find_inflection_node
    inflection = find_inflection_node(graph)
    events = [node.event for node in graph.nodes]
    flagged = sum(1 for e in events if e.risk_classification and e.risk_classification.has_any_flag())

    result = AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=inflection,
        total_events=len(events),
        flagged_events=flagged,
    )

    report_type = ReportType(request.report_type)
    builder = ReportBuilder()
    report_data = builder.build(domain_session, result, report_type=report_type)

    md = render_markdown(report_data)
    json_content = export_json(report_data)

    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=report_data.generated_at,
        report_type=report_type.value,
        content_markdown=md,
        content_json=json_content,
        generated_by="system",
    )
    db.add(report)
    db.flush()

    return {"id": report.id, "report_type": report.report_type}
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/api/test_reports.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add src/driftshield/api/routes/reports.py tests/api/test_reports.py
git commit -m "feat(reports): wire real report generation into API endpoint"
```

---

## Task 12.6: CLI Report Command

**Files:**
- Create: `src/driftshield/cli/commands/report.py`
- Create: `tests/cli/test_report_command.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_report_command.py
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


@pytest.fixture
def sample_transcript(tmp_path):
    """Create a minimal JSONL transcript file."""
    from datetime import datetime, timezone
    lines = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/test"}}
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "contents"}
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    ]
    filepath = tmp_path / "transcript.jsonl"
    filepath.write_text("\n".join(json.dumps(l) for l in lines))
    return filepath


def test_report_command_outputs_markdown(sample_transcript):
    result = runner.invoke(app, ["report", str(sample_transcript)])
    assert result.exit_code == 0
    assert "Forensic Analysis Report" in result.stdout


def test_report_command_summary_type(sample_transcript):
    result = runner.invoke(app, ["report", str(sample_transcript), "--type", "summary"])
    assert result.exit_code == 0
    assert "Forensic Analysis Report" in result.stdout
    assert "Risk State Transition Mapping" not in result.stdout
```

**Step 2: Run test to verify it fails**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/cli/test_report_command.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# src/driftshield/cli/commands/report.py
from pathlib import Path

import typer

from driftshield.cli.parsers import detect_parser, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.markdown import render_markdown
from driftshield.reports.models import ReportType

import uuid
from datetime import datetime, timezone


def report_command(
    path: Path = typer.Argument(..., help="Path to transcript file"),
    report_type: str = typer.Option("full", "--type", help="Report type: full or summary"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    parser_name: str | None = typer.Option(None, "--parser", help="Parser to use"),
):
    """Generate a forensic analysis report from a transcript."""
    if not path.exists():
        typer.echo(f"Error: {path} not found", err=True)
        raise typer.Exit(1)

    # Detect and run parser
    name = parser_name or detect_parser(path)
    parser = get_parser(name)
    content = path.read_text()
    events = parser.parse(content)

    if not events:
        typer.echo("No events found in transcript", err=True)
        raise typer.Exit(1)

    # Analyse
    result = analyze_session(events)
    session = DomainSession(
        id=events[0].session_id or uuid.uuid4(),
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp or datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )

    # Build and render report
    rt = ReportType(report_type)
    builder = ReportBuilder()
    report_data = builder.build(session, result, report_type=rt)
    md = render_markdown(report_data)

    if output:
        output.write_text(md)
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(md)
```

Register the command in `src/driftshield/cli/main.py`:

```python
from driftshield.cli.commands.report import report_command
app.command("report")(report_command)
```

**Step 4: Run test to verify it passes**

Run: `cd .worktrees/driftshield-v1/driftshield && python -m pytest tests/cli/test_report_command.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/driftshield/cli/ tests/cli/test_report_command.py
git commit -m "feat(cli): add report command for generating forensic reports"
```

---

## Task 12.7: Add Jinja2 Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add jinja2 to dependencies**

Add `"jinja2>=3.1.0"` to the `dependencies` list in `pyproject.toml`.

**Step 2: Install**

```bash
cd .worktrees/driftshield-v1/driftshield
pip install -e ".[dev]"
```

**Step 3: Run full test suite**

```bash
cd .worktrees/driftshield-v1/driftshield
python -m pytest -v
```

Expected: All tests pass.

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add jinja2 dependency for report generation"
```

Note: This task should be done first or alongside Task 12.3 in practice. Listed separately for clarity.
