"""Build lineage graphs from canonical events."""

from driftshield.core.models import CanonicalEvent
from driftshield.core.graph.models import DecisionNode, LineageGraph


def build_graph(events: list[CanonicalEvent], session_id: str) -> LineageGraph:
    """
    Build a LineageGraph from a list of CanonicalEvents.

    Events are sorted by timestamp and assigned sequence numbers.
    """
    graph = LineageGraph(session_id=session_id)

    # Sort events by timestamp
    sorted_events = sorted(events, key=lambda e: e.timestamp)

    # Create nodes with sequence numbers
    for seq_num, event in enumerate(sorted_events):
        node = DecisionNode(event=event, sequence_num=seq_num)
        graph.add_node(node)

    return graph
