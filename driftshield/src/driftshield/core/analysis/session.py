"""Session analysis orchestration."""

from dataclasses import dataclass

from driftshield.core.analysis.heuristics import (
    AssumptionMutationHeuristic,
    CoverageGapHeuristic,
    ConstraintViolationHeuristic,
    ContextContaminationHeuristic,
    PolicyDivergenceHeuristic,
    load_analysis_context,
)
from driftshield.core.analysis.inflection import select_inflection_node
from driftshield.core.analysis.risk import RiskAnalyzer
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.models import BreakPointStatus, CandidateBreakPoint, CanonicalEvent, ExplanationPayload
from driftshield.core.normalization import normalize_events


@dataclass
class AnalysisResult:
    """Result of analyzing a session."""

    events: list[CanonicalEvent]
    graph: LineageGraph
    inflection_node: DecisionNode | None
    total_events: int
    flagged_events: int
    inflection_explanation: ExplanationPayload | None = None
    candidate_break_point: CandidateBreakPoint | None = None

    @property
    def has_risks(self) -> bool:
        return self.flagged_events > 0

    @property
    def risk_summary(self) -> dict:
        summary = {
            "coverage_gap": 0,
            "assumption_mutation": 0,
            "context_contamination": 0,
            "policy_divergence": 0,
            "constraint_violation": 0,
        }

        for event in self.events:
            if event.risk_classification:
                for flag in event.risk_classification.active_flags():
                    if flag in summary:
                        summary[flag] += 1

        return summary


def analyze_session(
    events: list[CanonicalEvent],
    session_id: str | None = None,
) -> AnalysisResult:
    if not events:
        return AnalysisResult(
            events=[],
            graph=LineageGraph(session_id=session_id or "empty"),
            inflection_node=None,
            total_events=0,
            flagged_events=0,
            inflection_explanation=None,
            candidate_break_point=CandidateBreakPoint(
                status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
                summary="No clear break point detected because no observable events were available.",
                strategy="none",
                uncertainty_reasons=["no observable events were available"],
            ),
        )

    if session_id is None:
        session_id = events[0].session_id

    normalized_events = normalize_events(events)

    analyzer = RiskAnalyzer(
        heuristics=[
            CoverageGapHeuristic(),
            AssumptionMutationHeuristic(),
            PolicyDivergenceHeuristic(),
            ConstraintViolationHeuristic(),
            ContextContaminationHeuristic(),
        ],
        context_builders=[load_analysis_context],
    )
    analyzed_events = analyzer.analyze(normalized_events)
    graph = build_graph(analyzed_events, session_id=session_id)

    inflection_node = None
    inflection_explanation = None
    candidate_break_point = CandidateBreakPoint(
        status=BreakPointStatus.NO_CLEAR_BREAK_POINT,
        summary="No clear break point detected because no observable events were available.",
        strategy="none",
        uncertainty_reasons=["no observable events were available"],
    )
    if graph.nodes:
        last_node = graph.nodes[-1]
        selection = select_inflection_node(graph, last_node.id)
        candidate_break_point = selection.candidate_break_point
        if candidate_break_point.is_identified:
            inflection_node = selection.node
            inflection_explanation = selection.explanation

    flagged_count = sum(1 for event in analyzed_events if event.has_risk_flags())

    return AnalysisResult(
        events=analyzed_events,
        graph=graph,
        inflection_node=inflection_node,
        total_events=len(analyzed_events),
        flagged_events=flagged_count,
        inflection_explanation=inflection_explanation,
        candidate_break_point=candidate_break_point,
    )
