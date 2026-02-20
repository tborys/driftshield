"""Domain models for proprietary detection signatures."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class SignatureRiskClass(StrEnum):
    """Public taxonomy labels for signature grouping."""

    VARIABLE_DRIFT = "variable_drift"
    CONTEXT_CONTAMINATION = "context_contamination"
    TOOL_CONTRACT_VIOLATION = "tool_contract_violation"
    COVERAGE_GAP = "coverage_gap"
    POLICY_DIVERGENCE = "policy_divergence"
    UNVERIFIED_WRITE = "unverified_write"
    ASSUMPTION_MUTATION = "assumption_mutation"
    TOOL_MISSEQUENCING = "tool_missequencing"
    HALLUCINATION_DISTRACTION = "hallucination_distraction"
    CONSTRAINT_RELAXATION = "constraint_relaxation"


class SignatureStatus(StrEnum):
    """Lifecycle state for signatures."""

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    DEPRECATED = "deprecated"


@dataclass(slots=True)
class SignatureInvariant:
    """Invariant representation of a signature pattern."""

    graph_pattern: str
    temporal_constraints: list[str] = field(default_factory=list)
    state_constraints: list[str] = field(default_factory=list)
    lexical_markers: list[str] = field(default_factory=list)
    invariant_fingerprint: str = ""


@dataclass(slots=True)
class SignatureConfidence:
    """Confidence values from model and reviewer."""

    model_score: float
    reviewer_score: float | None = None


@dataclass(slots=True)
class SignatureProvenance:
    """Evidence source for a candidate/validated signature."""

    source_type: str
    source_ref: str
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class DetectionSignature:
    """Canonical signature definition for Post-V1 moat work."""

    signature_id: str
    title: str
    risk_class: SignatureRiskClass
    status: SignatureStatus
    invariant: SignatureInvariant
    confidence: SignatureConfidence
    provenance: list[SignatureProvenance]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.signature_id:
            raise ValueError("signature_id is required")
        if not self.invariant.invariant_fingerprint:
            raise ValueError("invariant_fingerprint is required")
        if not self.provenance:
            raise ValueError("at least one provenance source is required")
