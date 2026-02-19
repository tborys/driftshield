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
