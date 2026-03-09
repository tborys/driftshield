"""Concrete risk detection heuristics."""

from __future__ import annotations

from collections.abc import Iterable

from driftshield.core.analysis.risk import RiskHeuristic
from driftshield.core.models import CanonicalEvent, EventType, ExplanationPayload, RiskClassification


class CoverageGapHeuristic(RiskHeuristic):
    """Detect when output references fewer items than the input provided."""

    OUTPUT_PREFIXES = ["referenced_", "processed_", "reviewed_", "analyzed_", "checked_"]

    @property
    def name(self) -> str:
        return "coverage_gap"

    def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
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
        result: dict[str, list] = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, list) and value and all(isinstance(item, (str, int, float)) for item in value):
                result[full_key] = value
            elif isinstance(value, dict):
                result.update(self._find_lists_in_dict(value, full_key))
        return result

    def _find_matching_output_key(self, input_key: str, output_keys: list[str]) -> str | None:
        input_leaf = input_key.split(".")[-1]
        if input_key in output_keys:
            return input_key
        if input_leaf in output_keys:
            return input_leaf

        for output_key in output_keys:
            if output_key.split(".")[-1] == input_leaf:
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


class AssumptionMutationHeuristic(RiskHeuristic):
    """Detect assistant-introduced assumptions that silently drive a new planning step."""

    ASSUMPTION_KEYS = {"assumption", "assumptions", "plan", "strategy", "schedule", "approach"}
    PLANNING_TERMS = ("plan", "schedule", "rollout", "launch", "strategy", "approach")
    ASSUMPTION_CUES = ("assume", "assuming", "assumed", "guess", "likely", "probably", "maybe")

    @property
    def name(self) -> str:
        return "assumption_mutation"

    def check(
        self,
        event: CanonicalEvent,
        context: dict,
    ) -> RiskClassification | None:
        if event.event_type not in {EventType.TOOL_CALL, EventType.HANDOFF}:
            return None

        candidate = self._candidate_from_event(event)
        if candidate is None:
            return None

        if not self._is_planning_step(event):
            return None

        previous_events = context.get("previous_events", [])
        assistant_match = self._find_assistant_introduction(previous_events, candidate)
        if assistant_match is None:
            return None

        assistant_ref, candidate_text = assistant_match
        if self._was_user_requested(previous_events, candidate_text):
            return None

        return RiskClassification(
            assumption_mutation=True,
            explanations={
                "assumption_mutation": ExplanationPayload(
                    reason="An assistant-introduced assumption was carried forward into a new planning step without explicit user instruction.",
                    confidence=0.8,
                    evidence_refs=[assistant_ref, f"event:{len(previous_events) + 1}.inputs.{candidate[0]}", f"event:{len(previous_events) + 1}.action:{event.action}"],
                )
            },
        )

    def _candidate_from_event(self, event: CanonicalEvent) -> tuple[str, str] | None:
        for key, value in event.inputs.items():
            if key.lower() in self.ASSUMPTION_KEYS and isinstance(value, str) and value.strip():
                return key, value.strip().lower()
            if isinstance(value, str) and value.strip() and any(cue in value.lower() for cue in self.ASSUMPTION_CUES):
                return key, value.strip().lower()
        return None

    def _is_planning_step(self, event: CanonicalEvent) -> bool:
        action = event.action.lower()
        if any(term in action for term in self.PLANNING_TERMS):
            return True
        if any(key.lower() in self.ASSUMPTION_KEYS for key in event.inputs):
            return True
        haystacks = [str(v).lower() for v in event.inputs.values() if isinstance(v, str)]
        return any(term in haystack for haystack in haystacks for term in self.PLANNING_TERMS)

    def _find_assistant_introduction(
        self,
        previous_events: list[CanonicalEvent],
        candidate: tuple[str, str],
    ) -> tuple[str, str] | None:
        _, candidate_text = candidate

        for index in range(len(previous_events) - 1, -1, -1):
            previous_event = previous_events[index]
            if self._is_user_event(previous_event):
                continue

            for ref, text in self._iter_event_text(previous_event, index + 1):
                if candidate_text in text and any(cue in text for cue in self.ASSUMPTION_CUES):
                    return ref, candidate_text

        return None

    def _was_user_requested(self, previous_events: list[CanonicalEvent], candidate_text: str) -> bool:
        for index, previous_event in enumerate(previous_events, start=1):
            if not self._is_user_event(previous_event):
                continue
            for _, text in self._iter_event_text(previous_event, index):
                if candidate_text in text:
                    return True
        return False

    def _is_user_event(self, event: CanonicalEvent) -> bool:
        return event.agent_id.lower() == "user"

    def _iter_event_text(self, event: CanonicalEvent, event_index: int) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        refs.extend(self._flatten_strings(event.inputs, prefix=f"event:{event_index}.inputs"))
        refs.extend(self._flatten_strings(event.outputs, prefix=f"event:{event_index}.outputs"))
        return refs

    def _flatten_strings(self, value: object, prefix: str) -> list[tuple[str, str]]:
        flattened: list[tuple[str, str]] = []

        if isinstance(value, str):
            flattened.append((prefix, value.lower()))
            return flattened

        if isinstance(value, dict):
            for key, nested_value in value.items():
                flattened.extend(self._flatten_strings(nested_value, f"{prefix}.{key}"))
            return flattened

        if isinstance(value, list):
            for index, nested_value in enumerate(value):
                flattened.extend(self._flatten_strings(nested_value, f"{prefix}[{index}]"))
            return flattened

        return flattened


class ContextContaminationHeuristic(RiskHeuristic):
    """Detect when values from one context are incorrectly applied to another."""

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

    def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
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

    def _contexts_conflict(self, current: dict[str, str], previous: dict[str, str]) -> bool:
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
        return self._get_key_base(key1) == self._get_key_base(key2)


def load_analysis_context(previous_events: list[CanonicalEvent]) -> dict[str, list[dict[str, str]]]:
    """Load the minimal explicit rule/constraint context needed for heuristics."""
    project_rules: list[dict[str, str]] = []
    session_constraints: list[dict[str, str]] = []
    explicit_confirmations: list[dict[str, str]] = []

    for event in previous_events:
        for path, value in _walk_strings(event.outputs):
            lowered = value.lower()
            source_ref = f"event:{event.id}.outputs.{path}"
            if "force push" in lowered:
                project_rules.append({"rule_type": "forbid_force_push", "source_ref": source_ref, "rule_text": value})
            if any(marker in lowered for marker in ("approval required", "ask for confirmation", "confirm before destructive")):
                session_constraints.append({
                    "constraint_type": "requires_confirmation_for_destructive_actions",
                    "source_ref": source_ref,
                    "constraint_text": value,
                })
            if any(marker in lowered for marker in ("user confirmed", "approved", "yes, delete", "confirmed delete")):
                explicit_confirmations.append({
                    "confirmation_type": "destructive_action",
                    "source_ref": source_ref,
                    "text": value,
                })

    return {
        "project_rules": project_rules,
        "session_constraints": session_constraints,
        "explicit_confirmations": explicit_confirmations,
    }


def _walk_strings(value: object, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield prefix or "value", value
    elif isinstance(value, dict):
        for key, nested_value in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_strings(nested_value, nested_prefix)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            nested_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from _walk_strings(nested_value, nested_prefix)


def _normalise_text(value: object) -> str:
    return value.lower() if isinstance(value, str) else ""
