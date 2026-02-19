import uuid

from sqlalchemy.orm import Session as DBSession

from driftshield.core.models import (
    RiskClassification, Session as DomainSession,
)
from driftshield.core.analysis.session import AnalysisResult
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
