"""Risk classification heuristics for detecting decision failures."""

from abc import ABC, abstractmethod

from driftshield.core.models import CanonicalEvent, RiskClassification


class RiskHeuristic(ABC):
    """Base class for risk detection heuristics."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this heuristic."""
        ...

    @abstractmethod
    def check(
        self,
        event: CanonicalEvent,
        context: dict,
    ) -> RiskClassification | None:
        """
        Check if this event exhibits the risk pattern.

        Args:
            event: The event to analyze
            context: Dictionary with analysis context including:
                - previous_outputs: List of outputs from earlier events
                - previous_events: List of earlier CanonicalEvents

        Returns:
            RiskClassification with relevant flags set, or None if no risk detected
        """
        ...


class RiskAnalyzer:
    """Orchestrates running risk heuristics on events."""

    def __init__(self, heuristics: list[RiskHeuristic]):
        self.heuristics = heuristics

    def analyze(self, events: list[CanonicalEvent]) -> list[CanonicalEvent]:
        """
        Run all heuristics on each event and populate risk_classification.

        Args:
            events: List of events to analyze (should be in order)

        Returns:
            Same events with risk_classification populated where risks detected
        """
        previous_outputs: list[dict] = []
        previous_events: list[CanonicalEvent] = []

        for event in events:
            context = {
                "previous_outputs": list(previous_outputs),
                "previous_events": list(previous_events),
            }

            merged_risk = self._run_heuristics(event, context)

            if merged_risk is not None:
                event.risk_classification = merged_risk

            previous_outputs.append(event.outputs)
            previous_events.append(event)

        return events

    def _run_heuristics(
        self,
        event: CanonicalEvent,
        context: dict,
    ) -> RiskClassification | None:
        """Run all heuristics and merge results."""
        results: list[RiskClassification] = []

        for heuristic in self.heuristics:
            result = heuristic.check(event, context)
            if result is not None:
                results.append(result)

        if not results:
            return None

        return self._merge_classifications(results)

    def _merge_classifications(
        self,
        classifications: list[RiskClassification],
    ) -> RiskClassification:
        """Merge multiple RiskClassification instances (OR all flags)."""
        merged = RiskClassification()

        for classification in classifications:
            for field_name in RiskClassification.FLAG_FIELDS:
                if getattr(classification, field_name):
                    setattr(merged, field_name, True)

            merged.explanations.update(classification.explanations)

        return merged
