"""Inflection node detection."""

from uuid import UUID

from driftshield.core.graph.models import DecisionNode, LineageGraph


def find_inflection_node(
    graph: LineageGraph,
    failure_node_id: UUID,
) -> DecisionNode | None:
    """
    Find the inflection node by walking backward from failure.

    The inflection node is the first node with risk flags set,
    walking backward from the failure node toward the root.

    Args:
        graph: The lineage graph to search
        failure_node_id: ID of the node where failure was observed

    Returns:
        The inflection node, or None if no risky node found
    """
    path = graph.path_to_root(failure_node_id)

    if not path:
        return None

    for node in path:
        if node.has_risk_flags():
            return node

    return None
