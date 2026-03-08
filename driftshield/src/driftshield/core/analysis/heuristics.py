"""Concrete risk detection heuristics."""

from driftshield.core.analysis.risk import RiskHeuristic
from driftshield.core.models import CanonicalEvent, ExplanationPayload, RiskClassification


class CoverageGapHeuristic(RiskHeuristic):
    """
    Detects when an agent processes fewer items than provided in input.

    Pattern: Input contains enumerable items (list), output references
    a subset of those items, indicating potential missed coverage.
    """

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

        for input_key, input_items in input_lists.items():
            output_key = self._find_matching_output_key(input_key, list(output_lists.keys()))
            if output_key is None:
                continue

            output_items = output_lists[output_key]
            input_set = set(str(item) for item in input_items)
            output_set = set(str(item) for item in output_items)

            if output_set < input_set:
                return RiskClassification(
                    coverage_gap=True,
                    explanations={
                        "coverage_gap": ExplanationPayload(
                            reason="Output referenced fewer items than were provided in the input.",
                            confidence=0.86,
                            evidence_refs=[f"inputs.{input_key}", f"outputs.{output_key}"],
                        )
                    },
                )

        return None

    def _find_lists_in_dict(self, d: dict, prefix: str = "") -> dict[str, list]:
        result = {}

        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, list) and len(value) > 0:
                if all(isinstance(item, (str, int, float)) for item in value):
                    result[full_key] = value
            elif isinstance(value, dict):
                nested = self._find_lists_in_dict(value, full_key)
                result.update(nested)

        return result

    def _find_matching_output_key(
        self,
        input_key: str,
        output_keys: list[str],
    ) -> str | None:
        input_leaf = input_key.split(".")[-1]

        if input_key in output_keys:
            return input_key
        if input_leaf in output_keys:
            return input_leaf

        for output_key in output_keys:
            output_leaf = output_key.split(".")[-1]
            if output_leaf == input_leaf:
                return output_key

        for prefix in self.OUTPUT_PREFIXES:
            prefixed_leaf = f"{prefix}{input_leaf}"
            prefixed_key = f"{prefix}{input_key}"
            if prefixed_key in output_keys:
                return prefixed_key
            if prefixed_leaf in output_keys:
                return prefixed_leaf
            for output_key in output_keys:
                if output_key.split(".")[-1] == prefixed_leaf:
                    return output_key

        return None


class ContextContaminationHeuristic(RiskHeuristic):
    """Detects when values from one context are incorrectly applied to another."""

    CONTEXT_KEYS = [
        "category", "product_category", "discount_category",
        "tier", "customer_tier", "pricing_tier",
        "type", "product_type", "customer_type",
        "region", "market", "segment",
    ]

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
        previous_outputs = context.get("previous_outputs", [])

        if not previous_outputs:
            return None

        current_contexts = self._extract_context_values(event.inputs)
        current_values = self._extract_value_keys(event.inputs)

        if not current_contexts or not current_values:
            return None

        for prev_output in previous_outputs:
            prev_contexts = self._extract_context_values(prev_output)
            prev_values = self._extract_value_keys(prev_output)

            for value in current_values.values():
                for prev_value in prev_values.values():
                    if value == prev_value and self._contexts_conflict(current_contexts, prev_contexts):
                        return RiskClassification(
                            context_contamination=True,
                            explanations={
                                "context_contamination": ExplanationPayload(
                                    reason="A value from an earlier context appears to have been reused in a conflicting context.",
                                    confidence=0.82,
                                    evidence_refs=["context.previous_outputs", "inputs"],
                                )
                            },
                        )

        return None

    def _extract_context_values(self, d: dict) -> dict[str, str]:
        result = {}
        for key, value in d.items():
            key_lower = key.lower()
            for context_key in self.CONTEXT_KEYS:
                if context_key in key_lower and isinstance(value, str):
                    result[key] = value
                    break
        return result

    def _extract_value_keys(self, d: dict) -> dict[str, str]:
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
        for curr_key, curr_value in current.items():
            curr_key_base = self._get_key_base(curr_key)

            for prev_key, prev_value in previous.items():
                prev_key_base = self._get_key_base(prev_key)

                if curr_key_base == prev_key_base and curr_value != prev_value:
                    return True

                if self._keys_related(curr_key, prev_key) and curr_value != prev_value:
                    return True

        return False

    def _get_key_base(self, key: str) -> str:
        key_lower = key.lower()
        for context_key in self.CONTEXT_KEYS:
            if context_key in key_lower:
                return context_key
        return key_lower

    def _keys_related(self, key1: str, key2: str) -> bool:
        base1 = self._get_key_base(key1)
        base2 = self._get_key_base(key2)
        return base1 == base2
