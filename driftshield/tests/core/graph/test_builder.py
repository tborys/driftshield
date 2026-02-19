"""Tests for graph builder."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType
from driftshield.core.graph.builder import build_graph


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


class TestBuildGraph:
    def test_build_empty_graph(self):
        """Building from empty list returns empty graph."""
        graph = build_graph([], session_id="test")
        assert len(graph.nodes) == 0
        assert graph.session_id == "test"

    def test_build_single_node_graph(self):
        """Building from single event creates single-node graph."""
        event = make_event(session_id="s1", action="solo")
        graph = build_graph([event], session_id="s1")

        assert len(graph.nodes) == 1
        assert graph.root.action == "solo"
        assert graph.root.sequence_num == 0

    def test_build_linear_chain(self):
        """Building from chain of events preserves parent relationships."""
        event1 = make_event(session_id="s1", action="first")
        event2 = make_event(session_id="s1", action="second", parent_event_id=event1.id)
        event3 = make_event(session_id="s1", action="third", parent_event_id=event2.id)

        graph = build_graph([event1, event2, event3], session_id="s1")

        assert len(graph.nodes) == 3
        assert graph.root.action == "first"

        path = graph.path_to_root(event3.id)
        assert [n.action for n in path] == ["third", "second", "first"]

    def test_build_assigns_sequence_numbers_by_timestamp(self):
        """Sequence numbers are assigned based on timestamp order."""
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 1, 1, 10, 0, 2, tzinfo=timezone.utc)

        # Create out of order
        event2 = make_event(session_id="s1", action="second", timestamp=t2)
        event1 = make_event(session_id="s1", action="first", timestamp=t1)
        event3 = make_event(session_id="s1", action="third", timestamp=t3)

        graph = build_graph([event2, event1, event3], session_id="s1")

        nodes = graph.nodes  # should be in sequence order
        assert [n.action for n in nodes] == ["first", "second", "third"]
        assert [n.sequence_num for n in nodes] == [0, 1, 2]

    def test_build_with_branching(self):
        """Graph can have nodes with multiple children."""
        root = make_event(session_id="s1", action="root")
        child1 = make_event(session_id="s1", action="child1", parent_event_id=root.id)
        child2 = make_event(session_id="s1", action="child2", parent_event_id=root.id)

        graph = build_graph([root, child1, child2], session_id="s1")

        children = graph.get_children(root.id)
        assert len(children) == 2
        assert {c.action for c in children} == {"child1", "child2"}
