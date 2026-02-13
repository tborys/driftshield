"""Graph models for behavioral lineage."""

from dataclasses import dataclass
from uuid import UUID

from driftshield.core.models import CanonicalEvent, EventType


@dataclass
class DecisionNode:
    """A node in the behavioral lineage graph, wrapping a CanonicalEvent."""

    event: CanonicalEvent
    sequence_num: int
    is_inflection_node: bool = False

    @property
    def id(self) -> UUID:
        return self.event.id

    @property
    def action(self) -> str:
        return self.event.action

    @property
    def event_type(self) -> EventType:
        return self.event.event_type

    @property
    def inputs(self) -> dict:
        return self.event.inputs

    @property
    def outputs(self) -> dict:
        return self.event.outputs

    @property
    def parent_event_id(self) -> UUID | None:
        return self.event.parent_event_id

    def has_risk_flags(self) -> bool:
        return self.event.has_risk_flags()


@dataclass
class LineageGraph:
    """A directed acyclic graph of decision nodes representing reasoning trajectory."""

    session_id: str
    _nodes: dict = None  # UUID -> DecisionNode

    def __post_init__(self):
        if self._nodes is None:
            self._nodes = {}

    def add_node(self, node: DecisionNode) -> None:
        """Add a node to the graph."""
        self._nodes[node.id] = node

    def get_node(self, node_id: UUID) -> DecisionNode | None:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> list[DecisionNode]:
        """Return all nodes in sequence order."""
        return sorted(self._nodes.values(), key=lambda n: n.sequence_num)

    @property
    def root(self) -> DecisionNode | None:
        """Return the root node (sequence_num 0)."""
        for node in self._nodes.values():
            if node.sequence_num == 0:
                return node
        return None

    def get_children(self, node_id: UUID) -> list[DecisionNode]:
        """Get all nodes that have this node as parent."""
        return [
            node for node in self._nodes.values()
            if node.parent_event_id == node_id
        ]

    def get_parent(self, node_id: UUID) -> DecisionNode | None:
        """Get the parent node of a given node."""
        node = self.get_node(node_id)
        if node is None or node.parent_event_id is None:
            return None
        return self.get_node(node.parent_event_id)

    def path_to_root(self, node_id: UUID) -> list[DecisionNode]:
        """Return path from node to root, starting with the given node."""
        path = []
        current = self.get_node(node_id)

        while current is not None:
            path.append(current)
            current = self.get_parent(current.id)

        return path

    def path_between(self, start_id: UUID, end_id: UUID) -> list[DecisionNode]:
        """Return path from start to end, inclusive. Empty if not connected."""
        if start_id == end_id:
            node = self.get_node(start_id)
            return [node] if node else []

        # Walk backward from end to find start
        path_to_root = self.path_to_root(end_id)

        try:
            start_idx = next(
                i for i, node in enumerate(path_to_root)
                if node.id == start_id
            )
            # Reverse to get start -> end order
            return list(reversed(path_to_root[: start_idx + 1]))
        except StopIteration:
            return []
