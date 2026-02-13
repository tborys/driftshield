"""Tests for graph models."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.models import DecisionNode


def make_event(**kwargs) -> CanonicalEvent:
    """Factory for creating test events."""
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestDecisionNode:
    def test_create_from_event(self):
        """DecisionNode wraps a CanonicalEvent."""
        event = make_event(action="fetch_data")
        node = DecisionNode(event=event, sequence_num=1)

        assert node.event == event
        assert node.sequence_num == 1
        assert node.id == event.id
        assert node.action == "fetch_data"

    def test_node_delegates_to_event(self):
        """Node properties delegate to underlying event."""
        event = make_event(
            event_type=EventType.BRANCH,
            inputs={"x": 1},
            outputs={"y": 2},
        )
        node = DecisionNode(event=event, sequence_num=0)

        assert node.event_type == EventType.BRANCH
        assert node.inputs == {"x": 1}
        assert node.outputs == {"y": 2}
        assert node.parent_event_id == event.parent_event_id

    def test_has_risk_flags_delegates(self):
        """has_risk_flags delegates to event."""
        event_clean = make_event()
        node_clean = DecisionNode(event=event_clean, sequence_num=0)
        assert node_clean.has_risk_flags() is False

        event_risky = make_event(
            risk_classification=RiskClassification(assumption_mutation=True)
        )
        node_risky = DecisionNode(event=event_risky, sequence_num=0)
        assert node_risky.has_risk_flags() is True

    def test_is_inflection_node_default_false(self):
        """is_inflection_node defaults to False."""
        node = DecisionNode(event=make_event(), sequence_num=0)
        assert node.is_inflection_node is False

    def test_can_mark_as_inflection(self):
        """Can mark node as inflection point."""
        node = DecisionNode(event=make_event(), sequence_num=0, is_inflection_node=True)
        assert node.is_inflection_node is True
