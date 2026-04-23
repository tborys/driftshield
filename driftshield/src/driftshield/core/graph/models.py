"""Graph models for behavioral lineage."""

from dataclasses import dataclass, field
from uuid import UUID

from driftshield.core.models import CanonicalEvent, EventType


@dataclass
class LineageEdge:
    """A typed edge between two decision nodes in the lineage graph."""

    source_id: UUID
    target_id: UUID
    relationship: str = "explicit_parent"
    confidence: float = 1.0
    inferred: bool = False
    reason: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "relationship": self.relationship,
            "confidence": self.confidence,
            "inferred": self.inferred,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "LineageEdge | None":
        source_id = payload.get("source_id")
        target_id = payload.get("target_id")
        if not isinstance(source_id, str) or not isinstance(target_id, str):
            return None

        try:
            return cls(
                source_id=UUID(source_id),
                target_id=UUID(target_id),
                relationship=(
                    payload.get("relationship")
                    if isinstance(payload.get("relationship"), str)
                    else "explicit_parent"
                ),
                confidence=float(payload.get("confidence", 1.0)),
                inferred=bool(payload.get("inferred", False)),
                reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
                evidence_refs=[
                    str(ref)
                    for ref in payload.get("evidence_refs", [])
                    if isinstance(ref, str)
                ],
            )
        except (TypeError, ValueError):
            return None


@dataclass
class DecisionNode:
    """A node in the behavioral lineage graph, wrapping a CanonicalEvent."""

    event: CanonicalEvent
    sequence_num: int
    summary: str | None = None
    confidence: float | None = None
    evidence_refs: list[str] = field(default_factory=list)
    parent_ids: list[UUID] = field(default_factory=list)
    lineage_ambiguities: list[str] = field(default_factory=list)
    primary_parent_id: UUID | None = None
    is_inflection_node: bool = False

    def __post_init__(self) -> None:
        if self.summary is None:
            self.summary = self.event.summary or self.event.action
        if self.confidence is None:
            self.confidence = 0.7 if self.lineage_ambiguities else 1.0
        if not self.parent_ids:
            self.parent_ids = list(self.event.parent_event_refs or [])
        if self.primary_parent_id is None and self.parent_ids:
            self.primary_parent_id = self.parent_ids[0]
        if not self.lineage_ambiguities:
            self.lineage_ambiguities = list(self.event.ambiguities or [])

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
    def node_kind(self) -> str:
        return self.event.event_kind

    @property
    def inputs(self) -> dict:
        return self.event.inputs

    @property
    def outputs(self) -> dict:
        return self.event.outputs

    @property
    def parent_event_id(self) -> UUID | None:
        return self.primary_parent_id

    def has_risk_flags(self) -> bool:
        return self.event.has_risk_flags()


@dataclass
class LineageGraph:
    """A directed acyclic graph of decision nodes representing reasoning trajectory."""

    session_id: str
    _nodes: dict[UUID, DecisionNode] | None = None
    _edges: list[LineageEdge] | None = None

    def __post_init__(self) -> None:
        if self._nodes is None:
            self._nodes = {}
        if self._edges is None:
            self._edges = []

    def add_node(self, node: DecisionNode) -> None:
        """Add a node to the graph."""
        self._nodes[node.id] = node
        lineage = node.event.metadata.get("lineage") if node.event.metadata else None
        if isinstance(lineage, dict) and isinstance(lineage.get("incoming_edges"), list):
            return
        parent_ids = node.parent_ids or ([node.primary_parent_id] if node.primary_parent_id else [])
        for index, parent_id in enumerate(parent_ids):
            parent_node = self._nodes.get(parent_id)
            if parent_node is None or parent_node.sequence_num >= node.sequence_num:
                continue
            self.add_edge(
                LineageEdge(
                    source_id=parent_id,
                    target_id=node.id,
                    relationship="explicit_parent",
                    confidence=1.0,
                    evidence_refs=["parent_event_id" if index == 0 else f"parent_ids[{index}]"],
                )
            )

    def add_edge(self, edge: LineageEdge) -> None:
        """Add an edge to the graph, skipping exact duplicates."""
        for existing in self._edges:
            if (
                existing.source_id == edge.source_id
                and existing.target_id == edge.target_id
                and existing.relationship == edge.relationship
                and existing.reason == edge.reason
            ):
                if len(edge.evidence_refs) > len(existing.evidence_refs):
                    existing.evidence_refs = list(edge.evidence_refs)
                if edge.confidence != existing.confidence:
                    existing.confidence = edge.confidence
                if edge.inferred != existing.inferred:
                    existing.inferred = edge.inferred
                return
        self._edges.append(edge)

    def get_node(self, node_id: UUID) -> DecisionNode | None:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> list[DecisionNode]:
        """Return all nodes in sequence order."""
        return sorted(self._nodes.values(), key=lambda n: n.sequence_num)

    @property
    def edges(self) -> list[LineageEdge]:
        """Return all edges in target/source sequence order."""
        def _edge_sort_key(edge: LineageEdge) -> tuple[int, int]:
            target = self.get_node(edge.target_id)
            source = self.get_node(edge.source_id)
            return (
                target.sequence_num if target is not None else -1,
                source.sequence_num if source is not None else -1,
            )

        return sorted(self._edges, key=_edge_sort_key)

    @property
    def root_nodes(self) -> list[DecisionNode]:
        """Return root nodes in sequence order."""
        return [node for node in self.nodes if not self.incoming_edges(node.id)]

    @property
    def root(self) -> DecisionNode | None:
        """Return the first root node in sequence order."""
        roots = self.root_nodes
        return roots[0] if roots else None

    def incoming_edges(self, node_id: UUID) -> list[LineageEdge]:
        return [edge for edge in self.edges if edge.target_id == node_id]

    def outgoing_edges(self, node_id: UUID) -> list[LineageEdge]:
        return [edge for edge in self.edges if edge.source_id == node_id]

    def get_children(self, node_id: UUID) -> list[DecisionNode]:
        """Get all child nodes for a given node."""
        children: list[DecisionNode] = []
        for edge in self.outgoing_edges(node_id):
            child = self.get_node(edge.target_id)
            if child is not None:
                children.append(child)
        return children

    def get_parents(self, node_id: UUID) -> list[DecisionNode]:
        """Get all parent nodes for a given node."""
        parents: list[DecisionNode] = []
        for edge in self.incoming_edges(node_id):
            parent = self.get_node(edge.source_id)
            if parent is not None:
                parents.append(parent)
        return parents

    def get_parent(self, node_id: UUID) -> DecisionNode | None:
        """Get the primary parent node of a given node."""
        node = self.get_node(node_id)
        if node is None or node.primary_parent_id is None:
            return None
        return self.get_node(node.primary_parent_id)

    def path_to_root(self, node_id: UUID) -> list[DecisionNode]:
        """Return the primary path from node to root, starting with the given node."""
        path: list[DecisionNode] = []
        current = self.get_node(node_id)
        visited: set[UUID] = set()

        while current is not None and current.id not in visited:
            path.append(current)
            visited.add(current.id)
            current = self.get_parent(current.id)

        return path

    def path_between(self, start_id: UUID, end_id: UUID) -> list[DecisionNode]:
        """Return path from start to end, inclusive. Empty if not connected."""
        if start_id == end_id:
            node = self.get_node(start_id)
            return [node] if node else []

        path_to_root = self.path_to_root(end_id)

        try:
            start_idx = next(i for i, node in enumerate(path_to_root) if node.id == start_id)
            return list(reversed(path_to_root[: start_idx + 1]))
        except StopIteration:
            return []
