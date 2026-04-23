"""Build lineage graphs from canonical events."""

from uuid import UUID

from driftshield.core.models import CanonicalEvent
from driftshield.core.graph.models import DecisionNode, LineageEdge, LineageGraph


def build_graph(events: list[CanonicalEvent], session_id: str) -> LineageGraph:
    """
    Build a LineageGraph from a list of CanonicalEvents.

    Events are sorted by timestamp and assigned sequence numbers. Explicit parent
    references build the canonical DAG. When a normalized event has no usable
    parent reference, a low-confidence inferred edge keeps the lineage connected
    without pretending the source relationship is certain.
    """
    graph = LineageGraph(session_id=session_id)

    sorted_events = sorted(
        events,
        key=lambda e: (
            e.ordinal is None,
            e.ordinal if e.ordinal is not None else 0,
            e.timestamp,
        ),
    )

    sequence_by_id = {event.id: index for index, event in enumerate(sorted_events)}

    for seq_num, event in enumerate(sorted_events):
        node = DecisionNode(
            event=event,
            sequence_num=seq_num,
            summary=_node_summary(event),
            confidence=_node_confidence(event),
            evidence_refs=_node_evidence_refs(event),
            lineage_ambiguities=_node_ambiguities(event),
        )
        graph.add_node(node)

    for node in graph.nodes:
        incoming_edges = _incoming_edges(node, graph, sequence_by_id)
        node.parent_ids = [edge.source_id for edge in incoming_edges]
        node.primary_parent_id = _primary_parent_id(node, incoming_edges)
        node.lineage_ambiguities = _merge_ambiguities(node, incoming_edges)
        node.confidence = _node_confidence(node.event, incoming_edges=incoming_edges)
        if not node.evidence_refs:
            node.evidence_refs = _node_evidence_refs(node.event)

        for edge in incoming_edges:
            graph.add_edge(edge)

    return graph


def _lineage_payload(event: CanonicalEvent) -> dict[str, object]:
    payload = event.metadata.get("lineage") if event.metadata else None
    return payload if isinstance(payload, dict) else {}


def _node_summary(event: CanonicalEvent) -> str | None:
    lineage = _lineage_payload(event)
    summary = lineage.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    return event.summary or event.action


def _node_ambiguities(event: CanonicalEvent) -> list[str]:
    lineage = _lineage_payload(event)
    stored = lineage.get("lineage_ambiguities")
    if isinstance(stored, list):
        return [str(item) for item in stored if isinstance(item, str)]
    return list(event.ambiguities or [])


def _node_confidence(
    event: CanonicalEvent,
    *,
    incoming_edges: list[LineageEdge] | None = None,
) -> float:
    lineage = _lineage_payload(event)
    stored = lineage.get("confidence")
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return float(stored)

    ambiguities = _node_ambiguities(event)
    if incoming_edges:
        return min(edge.confidence for edge in incoming_edges)
    if ambiguities:
        return 0.7
    return 1.0


def _node_evidence_refs(event: CanonicalEvent) -> list[str]:
    lineage = _lineage_payload(event)
    stored = lineage.get("evidence_refs")
    if isinstance(stored, list):
        refs = [str(item) for item in stored if isinstance(item, str)]
        if refs:
            return refs

    refs = [f"event:{event.id}"]
    refs.extend(f"parent_event_refs[{idx}]" for idx, _ in enumerate(event.parent_event_refs))
    refs.extend(f"source_refs[{idx}]" for idx, _ in enumerate(event.source_refs))
    refs.extend(f"artifact_refs[{idx}]" for idx, _ in enumerate(event.artifact_refs))
    refs.extend(f"constraints[{idx}]" for idx, _ in enumerate(event.constraints))
    if event.tool_activity:
        refs.append("tool_activity")
    if event.failure_context:
        refs.append("failure_context")
        refs.extend(
            f"failure_context.signal:{signal}"
            for signal in event.failure_context.get("signals", [])
            if isinstance(signal, str)
        )
    refs.extend(f"ambiguity:{ambiguity}" for ambiguity in event.ambiguities)
    return refs


def _incoming_edges(
    node: DecisionNode,
    graph: LineageGraph,
    sequence_by_id: dict[UUID, int],
) -> list[LineageEdge]:
    persisted_edges = _persisted_incoming_edges(node.event)
    if persisted_edges:
        return persisted_edges

    explicit_parent_ids = _valid_parent_ids(node, sequence_by_id)
    if explicit_parent_ids:
        return [
            LineageEdge(
                source_id=parent_id,
                target_id=node.id,
                relationship="explicit_parent",
                confidence=1.0,
                evidence_refs=_explicit_edge_evidence_refs(node.event, parent_id),
            )
            for parent_id in explicit_parent_ids
        ]

    if node.sequence_num == 0:
        return []

    previous_node = graph.nodes[node.sequence_num - 1]
    reason = "missing_parent_ref"
    if node.event.parent_event_refs:
        reason = "missing_parent_target"
    return [
        LineageEdge(
            source_id=previous_node.id,
            target_id=node.id,
            relationship="inferred_sequence",
            confidence=0.35,
            inferred=True,
            reason=reason,
            evidence_refs=[
                f"event:{node.id}",
                f"node:{previous_node.id}",
                f"ambiguity:{reason}",
            ],
        )
    ]


def _persisted_incoming_edges(event: CanonicalEvent) -> list[LineageEdge]:
    lineage = _lineage_payload(event)
    payloads = lineage.get("incoming_edges")
    if not isinstance(payloads, list):
        return []

    edges: list[LineageEdge] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        edge = LineageEdge.from_dict(payload)
        if edge is not None:
            edges.append(edge)
    return edges


def _valid_parent_ids(node: DecisionNode, sequence_by_id: dict[UUID, int]) -> list[UUID]:
    parent_ids: list[UUID] = []
    for parent_id in node.event.parent_event_refs:
        parent_seq = sequence_by_id.get(parent_id)
        if parent_seq is None or parent_seq >= node.sequence_num:
            continue
        if parent_id not in parent_ids:
            parent_ids.append(parent_id)
    return parent_ids


def _explicit_edge_evidence_refs(event: CanonicalEvent, parent_id: UUID) -> list[str]:
    refs = [f"event:{event.id}", f"node:{parent_id}"]
    for idx, ref in enumerate(event.parent_event_refs):
        if ref == parent_id:
            refs.append(f"parent_event_refs[{idx}]")
    if event.parent_event_id == parent_id:
        refs.append("parent_event_id")
    if event.tool_activity:
        refs.append("tool_activity")
    return refs


def _primary_parent_id(node: DecisionNode, incoming_edges: list[LineageEdge]) -> UUID | None:
    lineage = _lineage_payload(node.event)
    stored = lineage.get("primary_parent_id")
    if isinstance(stored, str):
        try:
            return UUID(stored)
        except ValueError:
            pass

    if node.event.parent_event_id is not None:
        for edge in incoming_edges:
            if edge.source_id == node.event.parent_event_id:
                return edge.source_id

    return incoming_edges[0].source_id if incoming_edges else None


def _merge_ambiguities(node: DecisionNode, incoming_edges: list[LineageEdge]) -> list[str]:
    ambiguities = list(node.lineage_ambiguities)
    for edge in incoming_edges:
        if edge.reason and edge.reason not in ambiguities:
            ambiguities.append(edge.reason)
    return ambiguities
