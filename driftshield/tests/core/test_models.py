"""Tests for core domain models."""

from driftshield.core.models import EventType, RiskClassification


class TestEventType:
    def test_event_type_values_exist(self):
        """All expected event types are defined."""
        assert EventType.TOOL_CALL.value == "TOOL_CALL"
        assert EventType.BRANCH.value == "BRANCH"
        assert EventType.CONSTRAINT_CHECK.value == "CONSTRAINT_CHECK"
        assert EventType.ASSUMPTION.value == "ASSUMPTION"
        assert EventType.HANDOFF.value == "HANDOFF"
        assert EventType.OUTPUT.value == "OUTPUT"

    def test_event_type_is_string_enum(self):
        """EventType values are strings for JSON serialization."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)


class TestRiskClassification:
    def test_default_values_are_false(self):
        """All risk flags default to False."""
        risk = RiskClassification()
        assert risk.assumption_mutation is False
        assert risk.policy_divergence is False
        assert risk.constraint_violation is False
        assert risk.context_contamination is False
        assert risk.coverage_gap is False

    def test_can_set_individual_flags(self):
        """Individual flags can be set to True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        assert risk.assumption_mutation is True
        assert risk.policy_divergence is False
        assert risk.coverage_gap is True

    def test_has_any_flag(self):
        """has_any_flag returns True if any flag is set."""
        assert RiskClassification().has_any_flag() is False
        assert RiskClassification(assumption_mutation=True).has_any_flag() is True
        assert RiskClassification(coverage_gap=True).has_any_flag() is True

    def test_active_flags_returns_set_flags(self):
        """active_flags returns list of flag names that are True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        active = risk.active_flags()
        assert "assumption_mutation" in active
        assert "coverage_gap" in active
        assert "policy_divergence" not in active
        assert len(active) == 2
