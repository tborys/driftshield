# DriftShield V1 Design Document

**Date:** 2025-02-13
**Status:** Approved
**Author:** Demo User (CTO) + Claude

---

## 1. Overview

**DriftShield** is a self-hosted forensic analysis platform that reconstructs autonomous AI reasoning as structured behavioural lineage graphs, enabling deterministic root cause isolation for multi-step agent failures.

### Mission

As enterprises shift from copilots to autonomous AI agents, failures become systemic, multi-step, and legally consequential. Existing logging and tracing tools replay events but cannot structurally reconstruct reasoning drift or isolate inflection nodes of failure.

DriftShield converts reasoning trajectories into structured behavioural lineage graphs and risk-state transitions — enabling:

- Deterministic root cause isolation
- Systemic vs isolated failure classification
- Recurrence signature detection
- Drift alerts pre-material impact (future phase)

**Long-term vision:** Become the risk nervous system for autonomous AI.

### V1 Thesis

Before detecting emergent drift at scale, we must prove:

1. Reasoning transitions can be captured as structured decision nodes
2. Causal relationships can be reconstructed from existing logs
3. The resulting lineage graph provides forensic value that flat logs don't
4. Design partners find immediate value in this representation

**V1 is not about detecting subtle emergent drift at scale. V1 is about proving the structural abstraction works.**

---

## 2. Design Decisions & Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Architecture** | Monolith-first | Fastest to working product; simple self-hosted deployment (Docker Compose); proves boundaries before splitting; easier for agentic development. Can extract to services later when boundaries are proven. |
| **Deployment** | Self-hosted only | Enterprise customers won't send reasoning traces to third parties; regulatory requirements in fintech/insurance verticals. |
| **Integration (v1)** | Passive ingestion | Zero-friction adoption — just point at existing traces. Building toward sidecar integration in v2 for richer data. |
| **Input formats** | OTel, LangSmith, LangFuse, JSON | Agent-agnostic; define our own canonical model that others adapt to. Multiple parsers feeding single internal representation. |
| **Granularity** | Decision-level | Required for "inflection node" isolation. Turn-level too coarse, token-level overkill. Achievable from existing log formats. |
| **Storage** | PostgreSQL + recursive CTEs | Familiar ops story for self-hosted; handles graph traversal queries; Apache AGE available for v2 if needed. Document store (flexible schema) considered for v2. |
| **Stack** | Python (FastAPI) + TypeScript (React) | Python for analysis engine — strong for log parsing, ML-ready for Phase 2-3 recurrence modelling. TypeScript for UI layer. |
| **Primary persona (v1)** | Platform/ML engineers | Give them debugging and incident response tools first. Risk/compliance visibility comes in v2 once foundation proves value. |
| **UI model** | Investigation + Reports | Investigation view for exploration (drill down into lineage), one-click report generation for structured output. |

### Why Monolith-First (Detailed)

Alternative considered: service-oriented from start (separate ingest, analysis, storage, UI services).

Rejected because:
- 30-day goal is proving insight, not architectural elegance
- Single codebase easier for agentic development (Claude Code navigating/modifying)
- Self-hosted customers prefer simpler deployment (one Docker Compose file)
- Don't yet know where natural service boundaries are
- FastAPI + React monolith extracts cleanly to services later

---

## 3. Core Concepts

| Concept | Definition |
|---------|------------|
| **Decision Node** | A discrete point where an agent made a choice: tool call, branch taken, constraint evaluated, assumption introduced, or handoff executed. |
| **Behavioural Lineage Graph** | A directed acyclic graph of decision nodes connected by causal edges, representing the reasoning trajectory of an agent session. |
| **Inflection Node** | The decision node where reasoning first diverged from expected constraints — the root cause of downstream failure. |
| **Risk-State Transition** | A classified edge indicating assumption mutation, policy divergence, coverage gap, or constraint violation. |
| **Recurrence Signature** | A pattern of decision sequences appearing across multiple sessions, indicating systemic rather than isolated failure. |

---

## 4. Canonical Event Model

All ingested logs normalise to this structure:

```
CanonicalEvent {
  id: UUID
  session_id: string
  timestamp: ISO8601
  event_type: enum [TOOL_CALL, BRANCH, CONSTRAINT_CHECK, ASSUMPTION, HANDOFF, OUTPUT]
  agent_id: string
  parent_event_id: UUID | null  # causal predecessor

  payload: {
    action: string              # what happened
    inputs: object              # context/parameters
    outputs: object             # result/response
    metadata: object            # source-specific data
  }

  risk_classification: {
    assumption_mutation: bool
    policy_divergence: bool
    constraint_violation: bool
    context_contamination: bool
    coverage_gap: bool
  } | null  # populated by analysis engine
}
```

---

## 5. Architecture

### Directory Structure

```
driftshield/
├── api/                    # FastAPI application
│   ├── routes/
│   │   ├── ingest.py       # POST /ingest — receive logs
│   │   ├── sessions.py     # GET /sessions — list, search
│   │   ├── graphs.py       # GET /sessions/{id}/graph — lineage data
│   │   └── reports.py      # POST /sessions/{id}/report — generate
│   └── main.py
│
├── core/                   # Analysis engine (pure Python, no web deps)
│   ├── parsers/            # Log format adapters
│   │   ├── base.py         # Parser interface
│   │   ├── opentelemetry.py
│   │   ├── langsmith.py
│   │   ├── langfuse.py
│   │   └── json_logs.py
│   ├── graph/
│   │   ├── builder.py      # Constructs lineage graph from events
│   │   ├── models.py       # DecisionNode, Edge, Graph types
│   │   └── queries.py      # Traversal, path finding, inflection detection
│   ├── analysis/
│   │   ├── risk_classifier.py    # Classifies risk-state transitions
│   │   ├── inflection.py         # Detects inflection nodes
│   │   └── recurrence.py         # Signature matching across sessions
│   └── reports/
│       ├── generator.py    # Assembles forensic report
│       └── templates/      # Markdown/PDF templates
│
├── db/                     # PostgreSQL interaction
│   ├── models.py           # SQLAlchemy models
│   ├── migrations/         # Alembic migrations
│   └── queries.py          # Graph queries with recursive CTEs
│
├── ui/                     # React frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── LineageGraph.tsx    # Interactive graph visualisation
│   │   │   ├── NodeInspector.tsx   # Decision node detail panel
│   │   │   ├── SessionList.tsx     # Session browser
│   │   │   └── ReportPreview.tsx   # Report generation UI
│   │   └── pages/
│   │       ├── Investigation.tsx   # Main investigation view
│   │       └── Sessions.tsx        # Session list view
│   └── package.json
│
├── docker-compose.yml      # PostgreSQL + app
├── Dockerfile
└── pyproject.toml
```

### Data Flow

```
Logs (OTel/LangSmith/JSON)
         │
         ▼
    ┌─────────┐
    │ Parsers │ → CanonicalEvents
    └─────────┘
         │
         ▼
    ┌─────────────┐
    │ Graph Store │ (PostgreSQL)
    └─────────────┘
         │
         ▼
    ┌──────────────────┐
    │ Analysis Engine  │
    │ - Risk classify  │
    │ - Inflection     │
    │ - Recurrence     │
    └──────────────────┘
         │
         ▼
    ┌─────────────────┐
    │ UI / Reports    │
    └─────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Parsers** | Transform vendor-specific log formats into CanonicalEvents |
| **Graph Builder** | Constructs lineage graph from CanonicalEvents, establishing parent-child relationships |
| **Risk Classifier** | Analyses each transition and flags assumption mutations, coverage gaps, etc. |
| **Inflection Detector** | Walks graph backward from failure to identify first deviation point |
| **Recurrence Analyser** | Compares decision sequences across sessions to find systemic patterns |
| **Report Generator** | Produces structured Markdown/PDF forensic reports |
| **UI** | Investigation view (graph navigation) + report generation trigger |

---

## 6. Database Schema

### Core Tables

```sql
-- Agent sessions (one workflow execution)
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    external_id VARCHAR(255),          -- customer's session identifier
    agent_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status VARCHAR(50),                 -- running, completed, failed
    metadata JSONB,                     -- source-specific context
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Decision nodes (core unit of analysis)
CREATE TABLE decision_nodes (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    parent_node_id UUID REFERENCES decision_nodes(id),  -- causal edge
    sequence_num INTEGER NOT NULL,      -- ordering within session
    timestamp TIMESTAMPTZ NOT NULL,

    event_type VARCHAR(50) NOT NULL,    -- TOOL_CALL, BRANCH, CONSTRAINT_CHECK, etc.
    action VARCHAR(255) NOT NULL,       -- what happened
    inputs JSONB,
    outputs JSONB,
    metadata JSONB,

    -- Risk classification (populated by analysis)
    assumption_mutation BOOLEAN DEFAULT FALSE,
    policy_divergence BOOLEAN DEFAULT FALSE,
    constraint_violation BOOLEAN DEFAULT FALSE,
    context_contamination BOOLEAN DEFAULT FALSE,
    coverage_gap BOOLEAN DEFAULT FALSE,

    is_inflection_node BOOLEAN DEFAULT FALSE,  -- flagged by analysis

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Recurrence signatures (patterns across sessions)
CREATE TABLE recurrence_signatures (
    id UUID PRIMARY KEY,
    signature_hash VARCHAR(64) NOT NULL,  -- hash of decision sequence pattern
    pattern JSONB NOT NULL,               -- structured representation
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    severity VARCHAR(20),                 -- low, medium, high, critical
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Links sessions to signatures they contain
CREATE TABLE session_signatures (
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    signature_id UUID REFERENCES recurrence_signatures(id) ON DELETE CASCADE,
    matched_nodes UUID[],                 -- which nodes matched the pattern
    PRIMARY KEY (session_id, signature_id)
);

-- Forensic reports generated
CREATE TABLE reports (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    report_type VARCHAR(50),              -- full, summary, comparison
    content_markdown TEXT,
    content_json JSONB,                   -- structured data for UI
    generated_by VARCHAR(255)             -- user or system
);

-- Indexes for graph traversal
CREATE INDEX idx_decision_nodes_parent ON decision_nodes(parent_node_id);
CREATE INDEX idx_decision_nodes_session ON decision_nodes(session_id, sequence_num);
CREATE INDEX idx_decision_nodes_inflection ON decision_nodes(session_id) WHERE is_inflection_node = TRUE;
```

### Training Data Tables

```sql
-- Analyst decisions on inflection nodes (training signal)
CREATE TABLE inflection_validations (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,

    -- What the system suggested
    suggested_node_id UUID REFERENCES decision_nodes(id),
    suggested_confidence VARCHAR(20),    -- heuristic, low, medium, high

    -- What the analyst decided
    validated_node_id UUID REFERENCES decision_nodes(id),  -- NULL if "unclear"
    validation_status VARCHAR(20) NOT NULL,  -- confirmed, corrected, unclear

    -- Context for learning
    analyst_notes TEXT,                  -- free-form explanation
    correction_reason VARCHAR(100),      -- categorised: "subtle_assumption", "wrong_scope", etc.

    validated_by VARCHAR(255) NOT NULL,  -- analyst identifier
    validated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Risk flag validations (was this flag correct?)
CREATE TABLE risk_flag_validations (
    id UUID PRIMARY KEY,
    node_id UUID REFERENCES decision_nodes(id) ON DELETE CASCADE,

    flag_type VARCHAR(50) NOT NULL,      -- assumption_mutation, policy_divergence, etc.
    system_flagged BOOLEAN NOT NULL,     -- did system flag this?
    analyst_confirmed BOOLEAN NOT NULL,  -- did analyst agree?

    false_positive BOOLEAN GENERATED ALWAYS AS (system_flagged AND NOT analyst_confirmed) STORED,
    false_negative BOOLEAN GENERATED ALWAYS AS (NOT system_flagged AND analyst_confirmed) STORED,

    analyst_notes TEXT,
    validated_by VARCHAR(255) NOT NULL,
    validated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Recurrence signature validations
CREATE TABLE signature_validations (
    id UUID PRIMARY KEY,
    signature_id UUID REFERENCES recurrence_signatures(id) ON DELETE CASCADE,

    analyst_confirmed BOOLEAN NOT NULL,
    analyst_notes TEXT,
    suggested_refinement VARCHAR(20),    -- keep, broaden, narrow, split, merge

    validated_by VARCHAR(255) NOT NULL,
    validated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Local record of telemetry exports (audit trail)
CREATE TABLE telemetry_exports (
    id UUID PRIMARY KEY,
    exported_at TIMESTAMPTZ DEFAULT NOW(),
    export_type VARCHAR(50),           -- accuracy_rates, correction_reasons, etc.
    record_count INTEGER,
    payload_hash VARCHAR(64),          -- verify what was sent
    acknowledged BOOLEAN DEFAULT FALSE
);

-- Indexes for training data queries
CREATE INDEX idx_inflection_validations_status ON inflection_validations(validation_status);
CREATE INDEX idx_risk_flag_validations_type ON risk_flag_validations(flag_type, false_positive, false_negative);
```

### Graph Traversal Query Example

```sql
-- Find path from failure node back to inflection point
WITH RECURSIVE lineage AS (
    -- Start from the failed node
    SELECT id, parent_node_id, action, is_inflection_node, 1 as depth
    FROM decision_nodes
    WHERE id = :failure_node_id

    UNION ALL

    -- Walk backward through parents
    SELECT dn.id, dn.parent_node_id, dn.action, dn.is_inflection_node, l.depth + 1
    FROM decision_nodes dn
    JOIN lineage l ON dn.id = l.parent_node_id
    WHERE l.is_inflection_node = FALSE  -- stop at inflection node
)
SELECT * FROM lineage ORDER BY depth DESC;
```

---

## 7. Ingest Parsers

### Parser Interface

```python
from abc import ABC, abstractmethod
from typing import Iterator
from core.graph.models import CanonicalEvent

class BaseParser(ABC):
    """All log format parsers implement this interface."""

    @abstractmethod
    def can_parse(self, data: dict | list | str) -> bool:
        """Return True if this parser can handle the input format."""
        pass

    @abstractmethod
    def parse(self, data: dict | list | str) -> Iterator[CanonicalEvent]:
        """Transform raw log data into CanonicalEvents."""
        pass

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Human-readable format name for logging/UI."""
        pass
```

### V1 Parsers

| Parser | Input Format | Notes |
|--------|--------------|-------|
| `OpenTelemetryParser` | OTLP JSON export | Spans → decision nodes, parent_span_id → parent_node_id |
| `LangSmithParser` | LangSmith trace export | Runs → sessions, steps → nodes |
| `LangFuseParser` | LangFuse trace export | Similar structure to LangSmith |
| `JsonLogsParser` | Generic JSON lines | Configurable field mapping, fallback for custom formats |

### Auto-Detection Flow

```python
def ingest(raw_data: str | dict | list) -> Session:
    parsers = [
        OpenTelemetryParser(),
        LangSmithParser(),
        LangFuseParser(),
        JsonLogsParser(),  # fallback, most permissive
    ]

    for parser in parsers:
        if parser.can_parse(raw_data):
            events = list(parser.parse(raw_data))
            return build_session_from_events(events)

    raise UnsupportedFormatError("No parser matched input")
```

### Field Mapping for JsonLogsParser

For custom JSON logs, users provide a mapping config:

```yaml
# Example: mapping custom log format to canonical model
field_mappings:
  session_id: "trace_id"
  timestamp: "ts"
  event_type:
    field: "type"
    transform:
      "llm_call": "TOOL_CALL"
      "decision": "BRANCH"
      "check": "CONSTRAINT_CHECK"
  action: "event_name"
  inputs: "request"
  outputs: "response"
  parent_event_id: "parent_id"
```

---

## 8. Analysis Engine

### Risk Classification (V1 Heuristics)

| Risk Type | Detection Heuristic |
|-----------|---------------------|
| **Assumption Mutation** | Output introduces state/belief not present in inputs or parent context |
| **Policy Divergence** | Action contradicts known constraints (requires policy definition) |
| **Constraint Violation** | Explicit check failed but execution continued |
| **Context Contamination** | Inputs contain data from unrelated session/workflow |
| **Coverage Gap** | Input contains material content not referenced in reasoning output |

**V1 Approach:** Rule-based heuristics with manual review during concierge phase. Phase 2-3 adds ML-based classification trained on validated examples.

```python
class RiskClassifier:
    def __init__(self, policies: list[Policy] = None):
        self.policies = policies or []

    def classify(self, node: DecisionNode, parent: DecisionNode | None) -> RiskClassification:
        return RiskClassification(
            assumption_mutation=self._detect_assumption_mutation(node, parent),
            policy_divergence=self._detect_policy_divergence(node),
            constraint_violation=self._detect_constraint_violation(node),
            context_contamination=self._detect_context_contamination(node, parent),
            coverage_gap=self._detect_coverage_gap(node),
        )
```

### Inflection Node Detection

```python
def find_inflection_node(graph: LineageGraph, failure_node_id: UUID) -> DecisionNode | None:
    """
    Traverse backward from failure, return first node where reasoning diverged.

    Heuristic: First node in causal chain with any risk flag set,
    working backward from the failure.
    """
    path = graph.path_to_root(failure_node_id)

    for node in path:  # ordered from failure → root
        if node.has_risk_flags():
            return node

    return None  # no clear inflection point found
```

**V1 Limitation:** Inflection detection is heuristic. During concierge phase, analysts validate and correct, building training data for Phase 2 ML.

The UI shows the system's best guess with validation controls:

```
┌─────────────────────────────────────────────┐
│ Suggested Inflection Node                   │
│ ─────────────────────────────────────────── │
│ Node 3: interpret_query_result              │
│ Confidence: Heuristic (unvalidated)         │
│                                             │
│ [Confirm] [Select Different Node] [Unclear] │
└─────────────────────────────────────────────┘
```

### Coverage Gap Detection

For complex inputs (contracts, policies, documents):

```python
def detect_coverage_gap(node: DecisionNode) -> bool:
    """
    Flag when material input sections are unreferenced in output.
    """
    input_sections = parse_sections(node.inputs)
    output_references = extract_references(node.outputs)

    material_keywords = ["except", "notwithstanding", "provided that", "unless", "subject to"]

    for section in input_sections:
        if any(kw in section.text.lower() for kw in material_keywords):
            if not is_referenced(section, output_references):
                return True

    return False
```

### Recurrence Signature Detection

```python
def extract_signature(nodes: list[DecisionNode]) -> str:
    """
    Create a normalized hash of a decision sequence.
    Abstracts away specific values, captures structure.
    """
    pattern = [
        (node.event_type, normalize_action(node.action))
        for node in nodes
    ]
    return hash_pattern(pattern)

def find_recurrences(session: Session, min_occurrences: int = 2) -> list[RecurrenceMatch]:
    """
    Check if this session's failure signature appears elsewhere.
    """
    inflection = find_inflection_node(session.graph, session.failure_node_id)
    if not inflection:
        return []

    failure_path = session.graph.path_between(inflection.id, session.failure_node_id)
    signature = extract_signature(failure_path)

    return db.find_sessions_with_signature(signature, min_occurrences)
```

### Systemic vs Isolated Classification

| Classification | Criteria |
|----------------|----------|
| **Isolated** | Signature appears once, no pattern match |
| **Recurring** | Signature appears 2+ times, same agent |
| **Systemic** | Signature appears across multiple agents or workflows |

---

## 9. UI & Reports

### Investigation View

```
┌─────────────────────────────────────────────────────────────────────┐
│ DriftShield │ Session: abc-123 │ Agent: doc-reviewer │ FAILED      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Timeline                          │  Node Inspector               │
│  ─────────────────────────────     │  ───────────────────────────  │
│                                    │                               │
│  ● Node 1: receive_document   ──┐  │  Node 4: reasoning_step       │
│                                 │  │                               │
│  ● Node 2: extract_clauses    ──┤  │  Type: BRANCH                 │
│                                 │  │  Time: 14:32:12.847           │
│  ● Node 3: review_liability   ──┤  │                               │
│                                 │  │  Input context:               │
│  ◆ Node 4: review_indemnity   ──┤  │  ├─ Clause: 847 tokens        │
│    ⚠ Coverage Gap               │  │  ├─ Subsections: (a)(b)(c)(d) │
│    ⚠ Assumption Mutation        │  │  └─ (c): "except where..."    │
│    [SUGGESTED INFLECTION]       │  │                               │
│                                 │  │  Agent reasoning:             │
│  ● Node 5: generate_summary   ──┤  │  "Standard indemnification    │
│                                 │  │   structure, no flags"        │
│  ✖ Node 6: output             ──┘  │                               │
│    [LEGAL ESCALATION]              │  Risk Flags:                  │
│                                    │  ⚠ Coverage Gap               │
│                                    │    Subsection (c) unreferenced│
│                                    │  ⚠ Assumption Mutation        │
│                                    │    "Standard" unsupported     │
│                                    │                               │
│                                    │  [View Raw] [Compare Parent]  │
│                                    │                               │
├─────────────────────────────────────────────────────────────────────┤
│ [◀ Previous Session] [Generate Report] [Mark Reviewed]    [Next ▶] │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Interactions

| Action | Behaviour |
|--------|-----------|
| Click node | Show details in inspector panel |
| Click risk flag | Expand explanation of why flagged |
| Confirm/reject inflection | Records analyst decision, updates classification |
| Generate Report | Opens report preview, exports Markdown/PDF |
| Compare Parent | Side-by-side diff of inputs/outputs vs parent node |

### Report Structure

```markdown
# Forensic Analysis Report
**Session:** abc-123
**Agent:** doc-reviewer
**Generated:** 2025-02-13 14:45:00

## 1. Behavioral Lineage Reconstruction

Visual graph + table of decision nodes in sequence.

| # | Node | Type | Action | Risk Flags |
|---|------|------|--------|------------|
| 1 | receive_document | INPUT | Receive MSA contract | — |
| 2 | extract_clauses | TOOL_CALL | Parse key clauses | — |
| 3 | review_liability | BRANCH | Assess liability cap | — |
| 4 | review_indemnity | BRANCH | Assess indemnification | ⚠ Coverage, Assumption |
| 5 | generate_summary | TOOL_CALL | Compile findings | — |
| 6 | output | OUTPUT | Return recommendation | ✖ ESCALATED |

## 2. Inflection Node Identification

**Identified Node:** #4 (review_indemnity)
**Confidence:** Analyst-confirmed

**Analysis:** Agent processed 400-word indemnification clause containing
subsections (a) through (d). Subsection (c) contained material carve-out:
"except where claim arises from Customer-provided data or configurations."

Agent output summarised as "standard indemnification structure" without
surfacing the carve-out that materially limits coverage.

## 3. Risk-State Transition Mapping

- **Node 3 → Node 4:** Coverage gap introduced (subsection (c) unreferenced)
- **Node 4 → Node 5:** Assumption propagated ("standard" label carried forward)

## 4. Systemic Exposure Assessment

**Classification:** Isolated

No matching signatures found in other sessions.

## 5. Recurrence Risk Analysis

**Probability of Repetition:** Medium

**Contributing Factors:**
- Complex multi-subsection clauses processed as single unit
- No explicit coverage tracking for conditional language

**Recommendation:** Add heuristic to flag clauses containing "except",
"notwithstanding", "provided that" when not explicitly referenced in output.
```

---

## 10. V1 Validation Approach

### Synthetic Scenario Library

| Scenario | What It Tests |
|----------|---------------|
| **Coverage gap** | Agent receives complex input, summarises only part — system flags unreferenced content |
| **Assumption introduction** | Agent makes inference not in inputs — system captures where belief originated |
| **Cross-tool contamination** | Tool A output incorrectly influences Tool B — system shows causal chain |
| **Agent handoff drift** | Agent 1 passes summary to Agent 2, loses precision — system captures information loss |
| **Conflicting inputs** | Agent receives contradictory data, picks one silently — system flags decision point |

These are deliberately designed scenarios for internal validation, not emergent patterns requiring scale.

### Design Partner Engagement

Value proposition:

> "Bring us a recent incident where an agent did something unexpected. We'll reconstruct the reasoning lineage and show you exactly where the logic diverged — in a format you can query and share with your team."

Achievable with:
- Their existing logs (passive ingestion)
- Our lineage reconstruction
- Manual/semi-automated analysis
- Structured report output

---

## 11. V1 Scope

### Included

| Capability | Description |
|------------|-------------|
| Multi-format ingestion | OTel, LangSmith, LangFuse, JSON logs |
| Lineage graph construction | Decision nodes with causal edges |
| Risk classification | Heuristic-based flags for assumption mutation, coverage gaps, etc. |
| Inflection detection | Suggested inflection node with analyst validation |
| Investigation UI | Timeline view, node inspector, reasoning comparison |
| Report generation | Structured Markdown forensic reports |
| Training data capture | Analyst validations stored for Phase 2 |

### Excluded (Future Phases)

| Excluded | Phase | Rationale |
|----------|-------|-----------|
| Real-time alerting | 2-3 | Need validated heuristics first |
| ML-based classification | 2 | Need training data from v1 validations |
| Cross-customer pattern sharing | 3 | Privacy/legal complexity |
| Sidecar instrumentation | 2 | Start with passive ingestion for zero-friction adoption |
| Multi-tenant SaaS | 2+ | Self-hosted only for v1 |

---

## 12. Telemetry & Training Data Strategy

### On-Prem Data Stays On-Prem

Raw traces, session content, and customer data never leave customer infrastructure.

### Opt-In Anonymised Telemetry (v1.5+)

Customers can opt-in to share aggregated, anonymised signals:

**What gets shared (opt-in):**
- Heuristic accuracy rates (X% confirmed, Y% corrected)
- Correction reason distribution
- False positive/negative rates by flag type
- Structural patterns (abstracted, no content)

**What never leaves:**
- Raw inputs/outputs
- Session content
- Customer identifiers
- Actual decision node payloads

### Design Partner Agreements (v1)

Early design partners explicitly agree to share data for product development:

- Share anonymised session structures
- Share analyst validations
- Share correction patterns
- Optionally share raw trace content (case-by-case)

### Phase 3: Federated Learning

For customers wanting model improvements without data leaving:
- Training happens locally
- Only model updates (gradients) are shared
- Central model aggregates improvements

---

## 13. Deployment & Configuration

### Self-Hosted Deployment

```yaml
# docker-compose.yml
version: '3.8'

services:
  driftshield:
    image: driftshield/driftshield:latest
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/driftshield
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - db
    volumes:
      - ./config:/app/config

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=driftshield
      - POSTGRES_PASSWORD=password
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### Configuration

```yaml
# config/driftshield.yaml

ingest:
  enabled_parsers:
    - opentelemetry
    - langsmith
    - langfuse
    - json_logs

  json_logs:
    field_mappings: ./mappings/custom.yaml

analysis:
  risk_classification:
    assumption_mutation: true
    policy_divergence: true
    constraint_violation: true
    context_contamination: true
    coverage_gap: true

  heuristics:
    flag_exception_language: true
    flag_coverage_gaps: true
    min_coverage_ratio: 0.8

telemetry:
  enabled: false
  endpoint: https://telemetry.driftshield.io
```

---

## 14. Phased Roadmap

### Phase 1 — Forensic Infrastructure (0-6 months)

**Goal:** Become indispensable post-incident.

**Deliver:**
- Behavioral lineage reconstruction
- Inflection node detection (heuristic)
- Systemic vs isolated classification
- Investigation UI + report generation

### Phase 2 — Recurrence & Drift Detection (6-12 months)

**Add:**
- ML-based classification (trained on v1 validations)
- Deviation signature encoding
- Cross-workflow pattern detection
- Early-stage drift signals
- Sidecar instrumentation option

### Phase 3 — Runtime Risk Engine (12-24 months)

**Deliver:**
- In-flight risk scoring
- Drift threshold alerts
- Recurrence prediction
- Workflow gating capability
- Federated learning for privacy-preserving model improvement

---

## 15. Appendix: Example Scenario

### Contract Review Agent — Coverage Gap Detection

**Agent task:** "Review supplier contract and flag risks before legal sign-off"

```
Node 1: receive_contract
        Contract: Master Services Agreement with DataFlow Inc
        Type: SaaS infrastructure provider, 3-year term

Node 2: tool_call → extract_clauses
        Retrieved key clauses:
        - Liability cap: "12 months of fees paid"
        - Termination: "90 days written notice"
        - Data handling: "Processor under customer instruction"
        - Indemnification: [complex 400-word clause]

Node 3: reasoning_step
        "Reviewing liability cap..."
        Output: No flag

Node 4: reasoning_step
        "Reviewing termination..."
        Output: No flag

Node 5: reasoning_step
        "Reviewing data handling..."
        Output: No flag

Node 6: reasoning_step
        "Reviewing indemnification clause..."

        Agent's internal reasoning:
        "Indemnification covers IP infringement and data breach.
         Supplier indemnifies customer. Standard structure."

        Output: No flag
        ⚠ [INFLECTION - but agent marked as clean]

Node 7: output
        "Contract Review Complete
         Flags: None
         Recommendation: Proceed to signature"
        [SENT TO LEGAL]

---

Legal catches it on manual review: Indemnification clause has
carve-out in subsection (c): "...except where claim arises from
Customer-provided data or configurations."

For a data infrastructure provider, nearly ALL breach scenarios
involve customer data. The indemnification is effectively void.
```

**What DriftShield Shows:**

```
Node 6 — Reasoning Step Analysis

Input context:
├─ Indemnification clause: 847 tokens
├─ Contains subsections: (a), (b), (c), (d)
└─ Subsection (c): 94 tokens, contains "except where"

Agent reasoning trace:
├─ Referenced: "Supplier indemnifies customer"
├─ Referenced: "IP infringement and data breach"
├─ NOT referenced: Subsection (c) carve-out
└─ Conclusion: "Standard structure"

Risk Classification:
⚠ Coverage Gap
  - Input contained 4 subsections
  - Output referenced 3 of 4
  - Missing: Subsection (c) — contains "except where" pattern

⚠ Assumption Mutation
  - Agent introduced: "standard structure" assessment
  - Evidence gap: "Standard" label not supported by full clause analysis
```

**Forensic Value:**

After legal catches the carve-out manually, DriftShield analysis provides:

1. **This session:** Pinpoints Node 6 as inflection, shows exactly what was in context vs what was surfaced
2. **Mechanism identified:** Agent summarised complex clause without surfacing exception language
3. **Detection heuristic:** Flag when clause contains "except", "notwithstanding", "provided that" but reasoning output doesn't reference conditional

The third point — a concrete, testable heuristic — emerges from single-session forensic analysis and can be encoded for future detection.

---

*End of design document.*
