"""Inflection node detection."""

from dataclasses import dataclass
from uuid import UUID

from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.models import ExplanationPayload


@dataclass(frozen=True)
class InflectionSelection:
    """Selected inflection node plus scoring metadata."""

    node: DecisionNode | None
    explanation: ExplanationPayload | None
    strategy: str


_FLAG_WEIGHTS = {
    "constraint_violation": 4.0,
    "policy_divergence": 3.5,
    "context_contamination": 3.0,
    "assumption_mutation": 2.5,
    "coverage_gap": 2.0,
}


def _fallback_walkback_node(path: list[DecisionNode]) -> DecisionNode | None:
    for node in path:
        if node.has_risk_flags():
            return node
    return None


def _weighted_candidate_score(path: list[DecisionNode], idx: int) -> tuple[float, list[str]]:
    candidate = path[idx]
    risk = candidate.event.risk_classification
    active_flags = risk.active_flags() if risk is not None else []

    severity = sum(_FLAG_WEIGHTS.get(flag, 1.0) for flag in active_flags)

    downstream = path[:idx]
    downstream_flagged = [node for node in downstream if node.has_risk_flags()]
    compounding = max(0, len(downstream_flagged) - 1) * 2.5

    clean_after_candidate = sum(1 for node in downstream if not node.has_risk_flags())
    recovery_penalty = clean_after_candidate * 0.75

    proximity_bonus = max(0.0, 2.0 - (idx * 0.5))

    point_of_no_return = 0.0
    if not downstream:
        point_of_no_return += 1.0
    elif downstream_flagged and all(node.has_risk_flags() for node in downstream):
        point_of_no_return += 2.0

    score = severity + compounding + point_of_no_return + proximity_bonus - recovery_penalty

    reasons: list[str] = []
    if active_flags:
        reasons.append(f"severity from {', '.join(active_flags)}")
    if compounding:
        reasons.append(f"compounding risk through {len(downstream_flagged)} downstream flagged node(s)")
    if proximity_bonus:
        reasons.append("proximity to the observed failure")
    if point_of_no_return:
        reasons.append("point-of-no-return position near the observed failure")
    if recovery_penalty:
        reasons.append(f"recovery penalty for {clean_after_candidate} clean node(s) after this point")

    return score, reasons


def _selection_confidence(
    selected_score: float,
    alternate_score: float | None,
    strategy: str,
) -> float:
    """Map inflection scoring strength into the standard 0..1 confidence range."""
    if strategy == "walkback_fallback":
        return 0.5
    if alternate_score is None:
        return 1.0

    selected = max(selected_score, 0.0)
    alternate = max(alternate_score, 0.0)
    if selected == 0.0 and alternate == 0.0:
        return 0.5

    return round(selected / (selected + alternate), 2)


def select_inflection_node(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> InflectionSelection:
    """Select the most meaningful inflection node using weighted scoring with walkback fallback."""
    path = graph.path_to_root(failure_node_id)
    if not path:
        return InflectionSelection(node=None, explanation=None, strategy="none")

    flagged_candidates = [
        (idx, node)
        for idx, node in enumerate(path)
        if node.has_risk_flags()
    ]
    if not flagged_candidates:
        return InflectionSelection(node=None, explanation=None, strategy="none")

    scored: list[tuple[float, int, DecisionNode, list[str]]] = []
    for idx, node in flagged_candidates:
        score, reasons = _weighted_candidate_score(path, idx)
        scored.append((score, idx, node, reasons))

    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    best_score, _, best_node, best_reasons = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else None

    fallback_node = _fallback_walkback_node(path)
    fallback_idx = next((idx for idx, node in flagged_candidates if node.id == fallback_node.id), None) if fallback_node else None
    fallback_score = None
    if fallback_idx is not None and fallback_node is not None:
        fallback_score, _ = _weighted_candidate_score(path, fallback_idx)

    if fallback_node is None:
        return InflectionSelection(node=None, explanation=None, strategy="none")

    if (
        best_node.id != fallback_node.id
        and fallback_score is not None
        and (best_score - fallback_score) < 1.0
    ):
        best_node = fallback_node
        best_reasons = ["fallback to closest flagged node on the failure path"]
        strategy = "walkback_fallback"
    else:
        strategy = "weighted"

    confidence = _selection_confidence(
        selected_score=fallback_score if strategy == "walkback_fallback" and fallback_score is not None else best_score,
        alternate_score=best_score if strategy == "walkback_fallback" else runner_up_score,
        strategy=strategy,
    )

    risk = best_node.event.risk_classification
    active_flags = risk.active_flags() if risk is not None else []
    explanation = ExplanationPayload(
        reason=(
            "Selected as the inflection point using weighted scoring across severity, compounding risk, "
            "recovery opportunity, and point-of-no-return behaviour."
            if strategy == "weighted"
            else "Selected as the inflection point using fallback walkback to the closest flagged node on the path to failure."
        ),
        confidence=confidence,
        evidence_refs=[
            f"node:{best_node.id}",
            *[f"risk:{flag}" for flag in active_flags],
            *[f"inflection_reason:{reason}" for reason in best_reasons],
        ],
    )

    return InflectionSelection(node=best_node, explanation=explanation, strategy=strategy)


def find_inflection_node(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> DecisionNode | None:
    """
    Find the inflection node.

    Uses weighted scoring to pick the most meaningful divergence point and
    retains the historical backward-walk selection as a fallback path.
    """
    return select_inflection_node(graph, failure_node_id).node
