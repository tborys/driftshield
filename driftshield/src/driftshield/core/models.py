"""Core domain models for DriftShield."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
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
class ExplanationPayload:
    """Stable explanation shape for surfaced risk and inflection decisions."""

    reason: str
    confidence: float | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, payload: dict | None) -> "ExplanationPayload | None":
        if payload is None:
            return None
        return cls(
            reason=str(payload.get("reason", "")),
            confidence=payload.get("confidence"),
            evidence_refs=[str(ref) for ref in payload.get("evidence_refs", [])],
        )


@dataclass
class RiskClassification:
    """Risk flags for a decision node transition."""

    assumption_mutation: bool = False
    policy_divergence: bool = False
    constraint_violation: bool = False
    context_contamination: bool = False
    coverage_gap: bool = False
    explanations: dict[str, ExplanationPayload] = field(default_factory=dict)

    FLAG_FIELDS = (
        "assumption_mutation",
        "policy_divergence",
        "constraint_violation",
        "context_contamination",
        "coverage_gap",
    )

    def has_any_flag(self) -> bool:
        """Return True if any risk flag is set."""
        return any(getattr(self, field_name) for field_name in self.FLAG_FIELDS)

    def active_flags(self) -> list[str]:
        """Return list of flag names that are True."""
        return [field_name for field_name in self.FLAG_FIELDS if getattr(self, field_name)]

    def explanation_for(self, flag_name: str) -> ExplanationPayload | None:
        return self.explanations.get(flag_name)

    def explanations_as_dict(self) -> dict[str, dict[str, object]]:
        return {
            flag_name: explanation.to_dict()
            for flag_name, explanation in self.explanations.items()
            if flag_name in self.FLAG_FIELDS
        }

    @classmethod
    def explanations_from_dict(
        cls,
        payload: dict[str, dict] | None,
    ) -> dict[str, ExplanationPayload]:
        if not payload:
            return {}

        explanations: dict[str, ExplanationPayload] = {}
        for flag_name, explanation_payload in payload.items():
            if flag_name not in cls.FLAG_FIELDS:
                continue
            explanation = ExplanationPayload.from_dict(explanation_payload)
            if explanation is not None:
                explanations[flag_name] = explanation
        return explanations


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
    ordinal: int | None = None
    actor: dict[str, str] | None = None
    summary: str | None = None
    parent_event_refs: list[UUID] = field(default_factory=list)
    source_refs: list[dict[str, str]] = field(default_factory=list)
    artifact_refs: list[dict[str, str]] = field(default_factory=list)
    constraints: list[dict[str, str]] = field(default_factory=list)
    tool_activity: dict[str, Any] | None = None
    failure_context: dict[str, Any] | None = None
    ambiguities: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.inputs is None:
            self.inputs = {}
        if self.outputs is None:
            self.outputs = {}
        if self.metadata is None:
            self.metadata = {}
        if self.actor is None:
            self.actor = {
                "id": self.agent_id or "unknown",
                "role": self._default_actor_role(),
            }
        if self.parent_event_id is not None and not self.parent_event_refs:
            self.parent_event_refs = [self.parent_event_id]

    def has_risk_flags(self) -> bool:
        """Return True if this event has any risk flags set."""
        if self.risk_classification is None:
            return False
        return self.risk_classification.has_any_flag()

    @property
    def event_id(self) -> UUID:
        return self.id

    @property
    def event_kind(self) -> str:
        return self.event_type.value.lower()

    def to_normalized_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.id),
            "session_id": self.session_id,
            "ordinal": self.ordinal,
            "timestamp": self.timestamp.isoformat(),
            "event_kind": self.event_kind,
            "actor": dict(self.actor or {}),
            "summary": self.summary,
            "parent_event_refs": [str(ref) for ref in self.parent_event_refs],
            "source_refs": [dict(ref) for ref in self.source_refs],
            "artifact_refs": [dict(ref) for ref in self.artifact_refs],
            "constraints": [dict(ref) for ref in self.constraints],
            "tool_activity": dict(self.tool_activity or {}) if self.tool_activity else None,
            "failure_context": dict(self.failure_context or {}) if self.failure_context else None,
            "ambiguities": list(self.ambiguities),
        }

    def _default_actor_role(self) -> str:
        if self.agent_id == "user":
            return "user"
        if self.agent_id == "system":
            return "system"
        return "assistant"


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
