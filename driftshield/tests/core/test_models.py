"""Tests for core domain models."""

from driftshield.core.models import EventType


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
