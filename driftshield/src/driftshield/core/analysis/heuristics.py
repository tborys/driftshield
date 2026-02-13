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


class ContextContaminationHeuristic(RiskHeuristic):
    """
    Detects when values from one context are incorrectly applied to another.

    Pattern: A value (e.g., discount_tier) is retrieved with a specific context
    (e.g., category A), then applied in a different context (e.g., category B).

    Examples:
    - Gold discount for category A products applied to category B product
    - Enterprise support level applied to basic tier customer
    """

    # Keys that typically indicate context/scope
    CONTEXT_KEYS = [
        "category", "product_category", "discount_category",
        "tier", "customer_tier", "pricing_tier",
        "type", "product_type", "customer_type",
        "region", "market", "segment",
    ]

    # Keys that typically carry values that should match context
    VALUE_KEYS = [
        "discount_tier", "customer_discount_tier",
        "support_level", "service_level",
        "pricing_level", "rate",
    ]

    @property
    def name(self) -> str:
        return "context_contamination"

    def check(
        self,
        event: CanonicalEvent,
        context: dict,
    ) -> RiskClassification | None:
        """Check if values from previous context are misapplied."""
        previous_outputs = context.get("previous_outputs", [])

        if not previous_outputs:
            return None

        # Extract context and values from current event inputs
        current_contexts = self._extract_context_values(event.inputs)
        current_values = self._extract_value_keys(event.inputs)

        if not current_contexts or not current_values:
            return None

        # Look through previous outputs for context mismatches
        for prev_output in previous_outputs:
            prev_contexts = self._extract_context_values(prev_output)
            prev_values = self._extract_value_keys(prev_output)

            # Check if a value from previous output appears in current input
            # but the contexts don't match
            for value_key, value in current_values.items():
                # Find if this value came from a previous output
                for prev_value_key, prev_value in prev_values.items():
                    if value == prev_value:
                        # Value matches - now check if contexts match
                        if self._contexts_conflict(current_contexts, prev_contexts):
                            return RiskClassification(context_contamination=True)

        return None

    def _extract_context_values(self, d: dict) -> dict[str, str]:
        """Extract context-indicating key-value pairs."""
        result = {}
        for key, value in d.items():
            key_lower = key.lower()
            for context_key in self.CONTEXT_KEYS:
                if context_key in key_lower and isinstance(value, str):
                    result[key] = value
                    break
        return result

    def _extract_value_keys(self, d: dict) -> dict[str, str]:
        """Extract value-carrying key-value pairs."""
        result = {}
        for key, value in d.items():
            key_lower = key.lower()
            for value_key in self.VALUE_KEYS:
                if value_key in key_lower and isinstance(value, str):
                    result[key] = value
                    break
        return result

    def _contexts_conflict(
        self,
        current: dict[str, str],
        previous: dict[str, str],
    ) -> bool:
        """Check if contexts conflict (different values for similar keys)."""
        for curr_key, curr_value in current.items():
            curr_key_base = self._get_key_base(curr_key)

            for prev_key, prev_value in previous.items():
                prev_key_base = self._get_key_base(prev_key)

                # If keys refer to same concept but values differ -> conflict
                if curr_key_base == prev_key_base and curr_value != prev_value:
                    return True

                # Also check for category/type mismatches across related keys
                if self._keys_related(curr_key, prev_key) and curr_value != prev_value:
                    return True

        return False

    def _get_key_base(self, key: str) -> str:
        """Extract base concept from key (e.g., product_category -> category)."""
        key_lower = key.lower()
        for context_key in self.CONTEXT_KEYS:
            if context_key in key_lower:
                return context_key
        return key_lower

    def _keys_related(self, key1: str, key2: str) -> bool:
        """Check if two keys refer to related concepts."""
        # category and discount_category are related
        # tier and pricing_tier are related
        base1 = self._get_key_base(key1)
        base2 = self._get_key_base(key2)
        return base1 == base2
