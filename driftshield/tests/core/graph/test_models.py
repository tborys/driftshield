"""Tests for graph models."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.models import DecisionNode, LineageGraph


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


class TestLineageGraph:
    def test_create_empty_graph(self):
        """Can create an empty graph."""
        graph = LineageGraph(session_id="test-session")
        assert graph.session_id == "test-session"
        assert len(graph.nodes) == 0

    def test_add_node(self):
        """Can add nodes to graph."""
        graph = LineageGraph(session_id="test-session")
        event = make_event()
        node = DecisionNode(event=event, sequence_num=0)

        graph.add_node(node)

        assert len(graph.nodes) == 1
        assert graph.get_node(event.id) == node

    def test_get_node_by_id(self):
        """Can retrieve node by ID."""
        graph = LineageGraph(session_id="test-session")
        event = make_event()
        node = DecisionNode(event=event, sequence_num=0)
        graph.add_node(node)

        retrieved = graph.get_node(event.id)
        assert retrieved == node

    def test_get_nonexistent_node_returns_none(self):
        """Getting nonexistent node returns None."""
        graph = LineageGraph(session_id="test-session")
        assert graph.get_node(uuid4()) is None

    def test_nodes_in_sequence_order(self):
        """nodes property returns nodes in sequence order."""
        graph = LineageGraph(session_id="test-session")

        event1 = make_event(action="first")
        event2 = make_event(action="second")
        event3 = make_event(action="third")

        graph.add_node(DecisionNode(event=event2, sequence_num=1))
        graph.add_node(DecisionNode(event=event1, sequence_num=0))
        graph.add_node(DecisionNode(event=event3, sequence_num=2))

        nodes = graph.nodes
        assert [n.action for n in nodes] == ["first", "second", "third"]

    def test_root_node(self):
        """root property returns node with sequence_num 0."""
        graph = LineageGraph(session_id="test-session")

        event1 = make_event(action="root")
        event2 = make_event(action="child", parent_event_id=event1.id)

        graph.add_node(DecisionNode(event=event1, sequence_num=0))
        graph.add_node(DecisionNode(event=event2, sequence_num=1))

        assert graph.root.action == "root"

    def test_root_none_for_empty_graph(self):
        """root returns None for empty graph."""
        graph = LineageGraph(session_id="test-session")
        assert graph.root is None

    def test_get_children(self):
        """Can get child nodes of a node."""
        graph = LineageGraph(session_id="test-session")

        parent = make_event(action="parent")
        child1 = make_event(action="child1", parent_event_id=parent.id)
        child2 = make_event(action="child2", parent_event_id=parent.id)
        other = make_event(action="other")

        graph.add_node(DecisionNode(event=parent, sequence_num=0))
        graph.add_node(DecisionNode(event=child1, sequence_num=1))
        graph.add_node(DecisionNode(event=child2, sequence_num=2))
        graph.add_node(DecisionNode(event=other, sequence_num=3))

        children = graph.get_children(parent.id)
        assert len(children) == 2
        assert {c.action for c in children} == {"child1", "child2"}

    def test_get_parent(self):
        """Can get parent node."""
        graph = LineageGraph(session_id="test-session")

        parent = make_event(action="parent")
        child = make_event(action="child", parent_event_id=parent.id)

        graph.add_node(DecisionNode(event=parent, sequence_num=0))
        graph.add_node(DecisionNode(event=child, sequence_num=1))

        assert graph.get_parent(child.id).action == "parent"
        assert graph.get_parent(parent.id) is None
