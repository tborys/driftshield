import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DBSession

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    RiskClassification,
    Session as DomainSession,
    SessionStatus,
)
from driftshield.db.models import (
    DecisionNodeModel,
    RecurrenceSignatureModel,
    SessionModel,
    SessionSignatureModel,
)


@dataclass(frozen=True)
class IngestProvenance:
    transcript_hash: str
    source_session_id: str | None
    source_path: str | None
    parser_version: str
    ingested_at: datetime


@dataclass(frozen=True)
class IngestOutcome:
    session_id: uuid.UUID
    total_events: int
    flagged_events: int
    has_inflection: bool
    status: str
    deduplicated: bool


class PersistenceService:
    def __init__(self, db: DBSession):
        self._db = db

    def ingest(
        self,
        session: DomainSession,
        result: AnalysisResult,
        provenance: IngestProvenance,
    ) -> IngestOutcome:
        existing = self.get_ingest_outcome(provenance)
        if existing is not None:
            return existing

        self.save(session, result, provenance=provenance)
        return IngestOutcome(
            session_id=session.id,
            total_events=result.total_events,
            flagged_events=result.flagged_events,
            has_inflection=result.inflection_node is not None,
            status="created",
            deduplicated=False,
        )

    def get_ingest_outcome(self, provenance: IngestProvenance) -> IngestOutcome | None:
        existing = (
            self._db.query(SessionModel)
            .filter(
                SessionModel.transcript_hash == provenance.transcript_hash,
                SessionModel.parser_version == provenance.parser_version,
            )
            .one_or_none()
        )
        if existing is None:
            return None

        return self._outcome_for_existing_session(existing)

    def save(
        self,
        session: DomainSession,
        result: AnalysisResult,
        provenance: IngestProvenance | None = None,
    ) -> SessionModel:
        session_model = SessionModel(
            id=session.id,
            external_id=getattr(session, "external_id", None),
            agent_id=session.agent_id,
            started_at=session.started_at,
            ended_at=getattr(session, "ended_at", None),
            status=session.status.value,
            metadata_json=getattr(session, "metadata", None),
            transcript_hash=provenance.transcript_hash if provenance else None,
            source_session_id=provenance.source_session_id if provenance else None,
            source_path=provenance.source_path if provenance else None,
            parser_version=provenance.parser_version if provenance else None,
            ingested_at=provenance.ingested_at if provenance else None,
        )
        self._db.add(session_model)
        self._db.flush()

        for node in result.graph.nodes:
            risk = node.event.risk_classification or RiskClassification()
            is_inflection_node = (
                result.inflection_node is not None
                and node.id == result.inflection_node.id
            )
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
                risk_explanations=risk.explanations_as_dict() or None,
                is_inflection_node=is_inflection_node,
                inflection_explanation=(
                    result.inflection_explanation.to_dict()
                    if is_inflection_node and result.inflection_explanation is not None
                    else None
                ),
            )
            self._db.add(node_model)

        if result.recurrence is not None:
            recurrence = (
                self._db.query(RecurrenceSignatureModel)
                .filter(
                    RecurrenceSignatureModel.signature_hash
                    == result.recurrence.signature_hash
                )
                .one_or_none()
            )
            if recurrence is None:
                recurrence = RecurrenceSignatureModel(
                    signature_hash=result.recurrence.signature_hash,
                    pattern={
                        "level": result.recurrence.level.value,
                        "probability": result.recurrence.probability,
                    },
                    first_seen_at=session.started_at,
                    last_seen_at=session.started_at,
                    occurrence_count=result.recurrence.occurrence_count,
                    severity=result.recurrence.probability,
                )
                self._db.add(recurrence)
                self._db.flush()
            else:
                recurrence.last_seen_at = session.started_at
                recurrence.occurrence_count = result.recurrence.occurrence_count
                recurrence.severity = result.recurrence.probability

            mapping = SessionSignatureModel(
                session_id=session.id,
                signature_id=recurrence.id,
                matched_nodes=[],
            )
            self._db.add(mapping)

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
        graph = build_graph(events, session_id=str(session_id))

        for node in nodes:
            graph_node = graph.get_node(node.id)
            if graph_node is not None:
                graph_node.is_inflection_node = node.is_inflection_node

        return graph

    def list_sessions(
        self,
        page: int = 1,
        per_page: int = 20,
        flagged_only: bool = False,
        risk_class: str | None = None,
        source: str | None = None,
        since_hours: int | None = None,
    ) -> tuple[list[SessionModel], int]:
        query = self._db.query(SessionModel)

        if source:
            pattern = f"%{source.lower()}%"
            query = query.filter(
                or_(
                    SessionModel.source_path.ilike(pattern),
                    SessionModel.source_session_id.ilike(pattern),
                    SessionModel.parser_version.ilike(pattern),
                    SessionModel.agent_id.ilike(pattern),
                )
            )

        if since_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            query = query.filter(SessionModel.started_at >= cutoff)

        if flagged_only or risk_class:
            node_query = self._db.query(DecisionNodeModel.session_id)
            if risk_class:
                allowed_risk_classes = set(RiskClassification.FLAG_FIELDS)
                if risk_class not in allowed_risk_classes:
                    raise ValueError(f"Unsupported risk_class: {risk_class}")
                node_query = node_query.filter(getattr(DecisionNodeModel, risk_class).is_(True))
            else:
                node_query = node_query.filter(
                    or_(
                        DecisionNodeModel.assumption_mutation.is_(True),
                        DecisionNodeModel.policy_divergence.is_(True),
                        DecisionNodeModel.constraint_violation.is_(True),
                        DecisionNodeModel.context_contamination.is_(True),
                        DecisionNodeModel.coverage_gap.is_(True),
                    )
                )
            query = query.filter(
                SessionModel.id.in_(select(node_query.distinct().subquery().c.session_id))
            )

        query = query.order_by(SessionModel.started_at.desc())
        total = query.count()
        offset = (page - 1) * per_page
        sessions = query.offset(offset).limit(per_page).all()
        return sessions, total

    def _count_nodes(self, session_id: uuid.UUID) -> int:
        return (
            self._db.query(DecisionNodeModel)
            .filter(DecisionNodeModel.session_id == session_id)
            .count()
        )

    def _count_flagged_nodes(self, session_id: uuid.UUID) -> int:
        nodes = (
            self._db.query(DecisionNodeModel)
            .filter(DecisionNodeModel.session_id == session_id)
            .all()
        )
        return sum(
            1
            for node in nodes
            if any(
                [
                    node.assumption_mutation,
                    node.policy_divergence,
                    node.constraint_violation,
                    node.context_contamination,
                    node.coverage_gap,
                ]
            )
        )

    def _has_inflection(self, session_id: uuid.UUID) -> bool:
        return (
            self._db.query(DecisionNodeModel)
            .filter(
                DecisionNodeModel.session_id == session_id,
                DecisionNodeModel.is_inflection_node.is_(True),
            )
            .count()
            > 0
        )

    def _outcome_for_existing_session(self, session: SessionModel) -> IngestOutcome:
        return IngestOutcome(
            session_id=session.id,
            total_events=self._count_nodes(session.id),
            flagged_events=self._count_flagged_nodes(session.id),
            has_inflection=self._has_inflection(session.id),
            status="deduped",
            deduplicated=True,
        )


def _node_model_to_event(node: DecisionNodeModel, session_id: uuid.UUID) -> CanonicalEvent:
    metadata = dict(node.metadata_json or {})
    if node.inflection_explanation is not None:
        metadata["inflection_explanation"] = node.inflection_explanation

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
        metadata=metadata,
        risk_classification=RiskClassification(
            assumption_mutation=node.assumption_mutation,
            policy_divergence=node.policy_divergence,
            constraint_violation=node.constraint_violation,
            context_contamination=node.context_contamination,
            coverage_gap=node.coverage_gap,
            explanations=RiskClassification.explanations_from_dict(node.risk_explanations),
        ),
    )
