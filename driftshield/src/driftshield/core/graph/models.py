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
