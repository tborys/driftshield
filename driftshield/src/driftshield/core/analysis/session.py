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
from driftshield.core.analysis.recurrence import RecurrenceAssessment, RecurrenceEngine
from driftshield.core.analysis.risk import RiskAnalyzer
from driftshield.core.analysis.inflection import select_inflection_node
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.models import CanonicalEvent, ExplanationPayload


@dataclass
class AnalysisResult:
    """Result of analyzing a session."""

    events: list[CanonicalEvent]
    graph: LineageGraph
    inflection_node: DecisionNode | None
    total_events: int
    flagged_events: int
    recurrence: RecurrenceAssessment | None = None
    inflection_explanation: ExplanationPayload | None = None

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
    historical_recurrence_counts: dict[str, int] | None = None,
) -> AnalysisResult:
    if not events:
        return AnalysisResult(
            events=[],
            graph=LineageGraph(session_id=session_id or "empty"),
            inflection_node=None,
            total_events=0,
            flagged_events=0,
            recurrence=None,
            inflection_explanation=None,
        )

    if session_id is None:
        session_id = events[0].session_id

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
    analyzed_events = analyzer.analyze(events)
    graph = build_graph(analyzed_events, session_id=session_id)

    inflection_node = None
    inflection_explanation = None
    if graph.nodes:
        last_node = graph.nodes[-1]
        selection = select_inflection_node(graph, last_node.id)
        inflection_node = selection.node
        inflection_explanation = selection.explanation

    flagged_count = sum(1 for event in analyzed_events if event.has_risk_flags())

    recurrence = None
    if flagged_count > 0:
        recurrence = RecurrenceEngine().evaluate(
            analyzed_events,
            historical_counts=historical_recurrence_counts,
        )

    return AnalysisResult(
        events=analyzed_events,
        graph=graph,
        inflection_node=inflection_node,
        total_events=len(analyzed_events),
        flagged_events=flagged_count,
        recurrence=recurrence,
        inflection_explanation=inflection_explanation,
    )
