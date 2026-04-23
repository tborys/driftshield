"""Inflection node detection."""

from dataclasses import dataclass
from uuid import UUID

from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.models import BreakPointStatus, CandidateBreakPoint, ExplanationPayload


@dataclass(frozen=True)
class InflectionSelection:
    """Selected inflection node plus scoring metadata."""

    node: DecisionNode | None
    explanation: ExplanationPayload | None
    strategy: str
    candidate_break_point: CandidateBreakPoint
    score: float | None = None
    runner_up_score: float | None = None
    runner_up_node: DecisionNode | None = None


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


def _dedupe_refs(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for group in groups:
        for ref in group:
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _risk_evidence_refs(node: DecisionNode) -> list[str]:
    risk = node.event.risk_classification
    if risk is None:
        return []

    refs: list[str] = []
    for flag in risk.active_flags():
        explanation = risk.explanation_for(flag)
        if explanation is not None:
            refs.extend(explanation.evidence_refs)
    return refs


def _candidate_break_point_from_selection(
    *,
    node: DecisionNode | None,
    explanation: ExplanationPayload | None,
    strategy: str,
    score: float | None,
    runner_up_score: float | None,
    runner_up_node: DecisionNode | None,
) -> CandidateBreakPoint:
    if node is None or explanation is None:
        return CandidateBreakPoint(
            status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
            summary=(
                "No clear break point detected from observable run evidence because no flagged "
                "divergence step was found on the visible failure path."
            ),
            strategy=strategy,
            uncertainty_reasons=["no flagged divergence evidence was found on the observed path"],
        )

    risk = node.event.risk_classification
    risk_flags = risk.active_flags() if risk is not None else []
    uncertainty_reasons: list[str] = []
    if strategy == "walkback_fallback":
        uncertainty_reasons.append(
            "fallback selection was needed because the strongest visible candidates were too close"
        )
    if (
        score is not None
        and runner_up_score is not None
        and (score - runner_up_score) < 1.0
    ):
        uncertainty_reasons.append("competing flagged steps were similarly plausible")
    if node.lineage_ambiguities:
        uncertainty_reasons.append("selected step has lineage ambiguities")

    evidence_refs = _dedupe_refs(
        [f"node:{node.id}"],
        explanation.evidence_refs,
        list(node.evidence_refs),
        _risk_evidence_refs(node),
        [f"node:{runner_up_node.id}"] if runner_up_node is not None else [],
    )

    is_identified = (
        explanation.confidence is not None
        and explanation.confidence >= 0.6
        and strategy != "walkback_fallback"
    )

    if is_identified:
        return CandidateBreakPoint(
            status=BreakPointStatus.IDENTIFIED,
            summary=(
                f"Observable evidence suggests the run visibly broke at event "
                f"#{node.sequence_num} ({node.action})."
            ),
            node_id=node.id,
            sequence_num=node.sequence_num,
            action=node.action,
            confidence=explanation.confidence,
            evidence_refs=evidence_refs,
            risk_flags=risk_flags,
            uncertainty_reasons=uncertainty_reasons,
            strategy=strategy,
        )

    if not uncertainty_reasons:
        uncertainty_reasons.append("observable evidence was too weak to isolate one break point")

    return CandidateBreakPoint(
        status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
        summary=(
            "No clear break point detected from observable run evidence because the visible "
            "flagged steps were too weak or too close to distinguish confidently."
        ),
        confidence=explanation.confidence,
        evidence_refs=evidence_refs,
        uncertainty_reasons=uncertainty_reasons,
        strategy=strategy,
    )


def select_inflection_node(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> InflectionSelection:
    """Select the most meaningful inflection node using weighted scoring with walkback fallback."""
    path = graph.path_to_root(failure_node_id)
    if not path:
        return InflectionSelection(
            node=None,
            explanation=None,
            strategy="none",
            candidate_break_point=CandidateBreakPoint(
                status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
                summary=(
                    "No clear break point detected because no observable failure path was available."
                ),
                strategy="none",
                uncertainty_reasons=["no observable failure path was available"],
            ),
        )

    flagged_candidates = [
        (idx, node)
        for idx, node in enumerate(path)
        if node.has_risk_flags()
    ]
    if not flagged_candidates:
        return InflectionSelection(
            node=None,
            explanation=None,
            strategy="none",
            candidate_break_point=CandidateBreakPoint(
                status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
                summary=(
                    "No clear break point detected from observable run evidence because no "
                    "flagged divergence step was found on the visible failure path."
                ),
                strategy="none",
                uncertainty_reasons=["no flagged divergence evidence was found on the observed path"],
            ),
        )

    scored: list[tuple[float, int, DecisionNode, list[str]]] = []
    for idx, node in flagged_candidates:
        score, reasons = _weighted_candidate_score(path, idx)
        scored.append((score, idx, node, reasons))

    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    best_score, _, best_node, best_reasons = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else None
    runner_up_node = scored[1][2] if len(scored) > 1 else None

    fallback_node = _fallback_walkback_node(path)
    fallback_idx = next((idx for idx, node in flagged_candidates if node.id == fallback_node.id), None) if fallback_node else None
    fallback_score = None
    if fallback_idx is not None and fallback_node is not None:
        fallback_score, _ = _weighted_candidate_score(path, fallback_idx)

    if fallback_node is None:
        return InflectionSelection(
            node=None,
            explanation=None,
            strategy="none",
            candidate_break_point=CandidateBreakPoint(
                status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
                summary=(
                    "No clear break point detected from observable run evidence because no "
                    "supported flagged node was available on the visible failure path."
                ),
                strategy="none",
                uncertainty_reasons=["no supported flagged node was available"],
            ),
        )

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

    candidate_break_point = _candidate_break_point_from_selection(
        node=best_node,
        explanation=explanation,
        strategy=strategy,
        score=fallback_score if strategy == "walkback_fallback" else best_score,
        runner_up_score=best_score if strategy == "walkback_fallback" else runner_up_score,
        runner_up_node=runner_up_node,
    )

    return InflectionSelection(
        node=best_node,
        explanation=explanation,
        strategy=strategy,
        candidate_break_point=candidate_break_point,
        score=fallback_score if strategy == "walkback_fallback" else best_score,
        runner_up_score=best_score if strategy == "walkback_fallback" else runner_up_score,
        runner_up_node=runner_up_node,
    )


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


def select_candidate_break_point(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> CandidateBreakPoint:
    """Return the OSS-safe candidate break-point finding for a failed run."""
    return select_inflection_node(graph, failure_node_id).candidate_break_point
