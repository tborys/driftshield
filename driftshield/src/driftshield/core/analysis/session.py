"""Session analysis orchestration."""

from dataclasses import dataclass
from uuid import UUID

from driftshield.core.models import CanonicalEvent
from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.graph.builder import build_graph
from driftshield.core.analysis.risk import RiskAnalyzer
from driftshield.core.analysis.heuristics import (
    CoverageGapHeuristic,
    ContextContaminationHeuristic,
)
from driftshield.core.analysis.inflection import find_inflection_node
from driftshield.core.analysis.recurrence import RecurrenceAssessment, RecurrenceEngine


@dataclass
class AnalysisResult:
    """Result of analyzing a session."""

    events: list[CanonicalEvent]
    graph: LineageGraph
    inflection_node: DecisionNode | None
    total_events: int
    flagged_events: int
    recurrence: RecurrenceAssessment | None = None

    @property
    def has_risks(self) -> bool:
        """Return True if any risks were detected."""
        return self.flagged_events > 0

    @property
    def risk_summary(self) -> dict:
        """Return summary of detected risks."""
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
    """
    Analyze a session's events for risks and build lineage graph.

    Args:
        events: List of CanonicalEvents to analyze
        session_id: Optional session ID (defaults to first event's session_id)

    Returns:
        AnalysisResult with analyzed events, graph, and inflection node
    """
    if not events:
        return AnalysisResult(
            events=[],
            graph=LineageGraph(session_id=session_id or "empty"),
            inflection_node=None,
            total_events=0,
            flagged_events=0,
            recurrence=None,
        )

    # Determine session ID
    if session_id is None:
        session_id = events[0].session_id

    # Run risk analysis heuristics
    analyzer = RiskAnalyzer(
        heuristics=[
            CoverageGapHeuristic(),
            ContextContaminationHeuristic(),
        ]
    )
    analyzed_events = analyzer.analyze(events)

    # Build lineage graph
    graph = build_graph(analyzed_events, session_id=session_id)

    # Find inflection node (if any risks detected)
    inflection_node = None
    if graph.nodes:
        last_node = graph.nodes[-1]
        inflection_node = find_inflection_node(graph, last_node.id)

    # Count flagged events
    flagged_count = sum(1 for e in analyzed_events if e.has_risk_flags())

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
    )
