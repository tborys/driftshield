"""Concrete risk detection heuristics."""

from driftshield.core.models import CanonicalEvent, RiskClassification
from driftshield.core.analysis.risk import RiskHeuristic


class CoverageGapHeuristic(RiskHeuristic):
    """
    Detects when an agent processes fewer items than provided in input.

    Pattern: Input contains enumerable items (list), output references
    a subset of those items, indicating potential missed coverage.

    Examples:
    - Input has 4 subsections, output only references 3
    - Input has 5 clauses to review, output only mentions 4
    """

    # Common patterns for matching input/output key pairs
    OUTPUT_PREFIXES = ["referenced_", "processed_", "reviewed_", "analyzed_", "checked_"]

    @property
    def name(self) -> str:
        return "coverage_gap"

    def check(
        self,
        event: CanonicalEvent,
        context: dict,
    ) -> RiskClassification | None:
        """Check if output references fewer items than input provided."""
        input_lists = self._find_lists_in_dict(event.inputs)
        output_lists = self._find_lists_in_dict(event.outputs)

        if not input_lists or not output_lists:
            return None

        # Look for matching key patterns
        for input_key, input_items in input_lists.items():
            output_key = self._find_matching_output_key(input_key, output_lists.keys())

            if output_key is None:
                continue

            output_items = output_lists[output_key]

            # Check if output is a strict subset of input
            input_set = set(str(item) for item in input_items)
            output_set = set(str(item) for item in output_items)

            if output_set < input_set:  # Strict subset
                return RiskClassification(coverage_gap=True)

        return None

    def _find_lists_in_dict(self, d: dict, prefix: str = "") -> dict[str, list]:
        """Recursively find all lists in a dictionary, returning key -> list."""
        result = {}

        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, list) and len(value) > 0:
                # Only include lists of simple values (strings, numbers)
                if all(isinstance(item, (str, int, float)) for item in value):
                    result[key] = value

            elif isinstance(value, dict):
                # Recurse into nested dicts
                nested = self._find_lists_in_dict(value, full_key)
                result.update(nested)

        return result

    def _find_matching_output_key(
        self,
        input_key: str,
        output_keys: list[str],
    ) -> str | None:
        """Find an output key that matches the input key pattern."""
        # Direct match
        if input_key in output_keys:
            return input_key

        # Check common prefixes: items -> processed_items, referenced_items, etc.
        for prefix in self.OUTPUT_PREFIXES:
            prefixed_key = f"{prefix}{input_key}"
            if prefixed_key in output_keys:
                return prefixed_key

        return None
