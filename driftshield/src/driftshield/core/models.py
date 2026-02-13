"""Core domain models for DriftShield."""

from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from uuid import UUID


class EventType(str, Enum):
    """Types of decision nodes in a reasoning trace."""

    TOOL_CALL = "TOOL_CALL"
    BRANCH = "BRANCH"
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"
    ASSUMPTION = "ASSUMPTION"
    HANDOFF = "HANDOFF"
    OUTPUT = "OUTPUT"


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
