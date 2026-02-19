import uuid

from sqlalchemy.orm import Session as DBSession

from driftshield.core.models import (
    CanonicalEvent, EventType, RiskClassification,
    Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.models import LineageGraph
from driftshield.core.graph.builder import build_graph
from driftshield.db.models import SessionModel, DecisionNodeModel


class PersistenceService:
    def __init__(self, db: DBSession):
        self._db = db

    def save(self, session: DomainSession, result: AnalysisResult) -> SessionModel:
        session_model = SessionModel(
            id=session.id,
            external_id=getattr(session, "external_id", None),
            agent_id=session.agent_id,
            started_at=session.started_at,
            ended_at=getattr(session, "ended_at", None),
            status=session.status.value,
            metadata_json=getattr(session, "metadata", None),
        )
        self._db.add(session_model)
        self._db.flush()

        for node in result.graph.nodes:
            risk = node.event.risk_classification or RiskClassification()
            node_model = DecisionNodeModel(
                id=node.id,
                session_id=session.id,
                parent_node_id=node.parent_event_id,
                sequence_num=node.sequence_num,
                timestamp=node.event.timestamp,
                event_type=node.event_type.value,
                action=node.action,
                inputs=node.inputs,
                outputs=node.outputs,
                metadata_json=node.event.metadata,
                assumption_mutation=risk.assumption_mutation,
                policy_divergence=risk.policy_divergence,
                constraint_violation=risk.constraint_violation,
                context_contamination=risk.context_contamination,
                coverage_gap=risk.coverage_gap,
                is_inflection_node=(
                    result.inflection_node is not None
                    and node.id == result.inflection_node.id
                ),
            )
            self._db.add(node_model)

        return session_model

    def load_session(self, session_id: uuid.UUID) -> DomainSession | None:
        model = self._db.get(SessionModel, session_id)
        if model is None:
            return None
        return DomainSession(
            id=model.id,
            agent_id=model.agent_id or "",
            started_at=model.started_at,
            status=SessionStatus(model.status),
        )

    def load_graph(self, session_id: uuid.UUID) -> LineageGraph | None:
        nodes = (
            self._db.query(DecisionNodeModel)
            .filter(DecisionNodeModel.session_id == session_id)
            .order_by(DecisionNodeModel.sequence_num)
            .all()
        )
        if not nodes:
            return None

        events = [_node_model_to_event(n, session_id) for n in nodes]
        return build_graph(events, session_id=str(session_id))

    def list_sessions(
        self, page: int = 1, per_page: int = 20
    ) -> tuple[list[SessionModel], int]:
        query = self._db.query(SessionModel).order_by(SessionModel.started_at.desc())
        total = query.count()
        offset = (page - 1) * per_page
        sessions = query.offset(offset).limit(per_page).all()
        return sessions, total


def _node_model_to_event(node: DecisionNodeModel, session_id: uuid.UUID) -> CanonicalEvent:
    return CanonicalEvent(
        id=node.id,
        session_id=str(session_id),
        timestamp=node.timestamp,
        event_type=EventType(node.event_type),
        agent_id="",
        action=node.action,
        parent_event_id=node.parent_node_id,
        inputs=node.inputs,
        outputs=node.outputs,
        metadata=node.metadata_json,
        risk_classification=RiskClassification(
            assumption_mutation=node.assumption_mutation,
            policy_divergence=node.policy_divergence,
            constraint_violation=node.constraint_violation,
            context_contamination=node.context_contamination,
            coverage_gap=node.coverage_gap,
        ),
    )
