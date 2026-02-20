"""Quality gate evaluator for candidate signature acceptance."""

from dataclasses import dataclass


@dataclass(slots=True)
class QualityGateInput:
    evidence_completeness: float
    ambiguity: float
    duplicate_similarity: float
    reviewer_verdict: str


@dataclass(slots=True)
class QualityGateResult:
    passed: bool
    bucket: str
    score: float
    reasons: list[str]


class QualityGateEvaluator:
    """Evaluate signature candidates using weighted, auditable quality checks."""

    def __init__(
        self,
        *,
        evidence_weight: float = 0.5,
        ambiguity_weight: float = 0.3,
        duplicate_weight: float = 0.2,
    ) -> None:
        self.evidence_weight = evidence_weight
        self.ambiguity_weight = ambiguity_weight
        self.duplicate_weight = duplicate_weight

    def evaluate(self, payload: QualityGateInput) -> QualityGateResult:
        reasons: list[str] = []

        score = (
            payload.evidence_completeness * self.evidence_weight
            + (1 - payload.ambiguity) * self.ambiguity_weight
            + (1 - payload.duplicate_similarity) * self.duplicate_weight
        )

        if payload.reviewer_verdict != "accept":
            reasons.append("reviewer_verdict")

        if payload.evidence_completeness < 0.8:
            reasons.append("evidence_completeness")

        if payload.ambiguity > 0.25:
            reasons.append("ambiguity")

        if payload.duplicate_similarity > 0.5:
            reasons.append("duplicate_similarity")

        if not reasons and score >= 0.85:
            return QualityGateResult(passed=True, bucket="auto_accept", score=score, reasons=[])

        return QualityGateResult(
            passed=False,
            bucket="needs_review",
            score=score,
            reasons=reasons,
        )
