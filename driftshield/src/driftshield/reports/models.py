import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from driftshield.core.models import CandidateBreakPoint


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
class ReportSummary:
    headline: str = ""
    what_happened: str = ""
    where_it_broke: str = ""
    evidence_basis: str = ""
    confidence: float | None = None
    confidence_label: str = "unknown"
    uncertainty: list[str] = field(default_factory=list)
    pattern_resemblance: str = ""
    oss_safety_note: str = ""


@dataclass
class ReportFinding:
    finding_id: str
    finding_kind: str
    subject_ref: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    status: str = "reported"


@dataclass
class PatternMatch:
    match_id: str
    signature_id: str
    mechanism_id: str
    signature_layer: dict[str, Any]
    scope_ref: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    rationale: str = ""
    source: str = "local"


@dataclass
class EvidenceRef:
    ref_id: str
    target_kind: str
    target_ref: str
    role: str
    excerpt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportData:
    session_id: uuid.UUID
    agent_id: str
    generated_at: datetime
    report_type: ReportType
    sections: list[ReportSection]
    inflection_node_id: uuid.UUID | None = None
    inflection_action: str | None = None
    candidate_break_point: CandidateBreakPoint | None = None
    total_events: int = 0
    flagged_events: int = 0
    classification: str = "isolated"
    schema_version: str = "forensic_report.v1"
    summary: ReportSummary = field(default_factory=ReportSummary)
    findings: list[ReportFinding] = field(default_factory=list)
    pattern_matches: list[PatternMatch] = field(default_factory=list)
    evidence_index: list[EvidenceRef] = field(default_factory=list)
