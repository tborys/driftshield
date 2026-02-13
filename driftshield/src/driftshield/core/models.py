"""Core domain models for DriftShield."""

from dataclasses import dataclass, fields
from enum import Enum


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
