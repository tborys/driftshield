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
    SessionModel,
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
        existing_session_id: uuid.UUID | None = None,
    ) -> IngestOutcome:
        if existing_session_id is not None:
            existing_session = self._db.get(SessionModel, existing_session_id)
            if existing_session is not None and (
                existing_session.transcript_hash == provenance.transcript_hash
                and existing_session.parser_version == provenance.parser_version
            ):
                return self._outcome_for_existing_session(existing_session)

            duplicate = self.get_ingest_outcome(provenance)
            if duplicate is not None and duplicate.session_id != existing_session_id:
                return duplicate

            self.upsert(session, result, provenance=provenance)
            return IngestOutcome(
                session_id=session.id,
                total_events=result.total_events,
                flagged_events=result.flagged_events,
                has_inflection=result.inflection_node is not None,
                status="updated" if existing_session is not None else "created",
                deduplicated=False,
            )

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
        session_model = SessionModel(id=session.id)
        self._apply_session_fields(
            session_model,
            session=session,
            provenance=provenance,
        )
        self._db.add(session_model)
        self._db.flush()
        self._save_result(session, result)
        return session_model

    def upsert(
        self,
        session: DomainSession,
        result: AnalysisResult,
        provenance: IngestProvenance | None = None,
    ) -> SessionModel:
        session_model = self._db.get(SessionModel, session.id)
        if session_model is None:
            return self.save(session, result, provenance=provenance)

        self._apply_session_fields(
            session_model,
            session=session,
            provenance=provenance,
        )
        self._replace_session_result(session.id)
        self._save_result(session, result)
        return session_model

    def _apply_session_fields(
        self,
        session_model: SessionModel,
        *,
        session: DomainSession,
        provenance: IngestProvenance | None,
    ) -> None:
        session_model.external_id = getattr(session, "external_id", None)
        session_model.agent_id = session.agent_id
        session_model.started_at = session.started_at
        session_model.ended_at = getattr(session, "ended_at", None)
        session_model.status = session.status.value
        session_model.metadata_json = getattr(session, "metadata", None)
        session_model.transcript_hash = provenance.transcript_hash if provenance else None
        session_model.source_session_id = provenance.source_session_id if provenance else None
        session_model.source_path = provenance.source_path if provenance else None
        session_model.parser_version = provenance.parser_version if provenance else None
        session_model.ingested_at = provenance.ingested_at if provenance else None

    def _replace_session_result(self, session_id: uuid.UUID) -> None:
        (
            self._db.query(DecisionNodeModel)
            .filter(DecisionNodeModel.session_id == session_id)
            .delete(synchronize_session=False)
        )
        self._db.flush()

    def _save_result(
        self,
        session: DomainSession,
        result: AnalysisResult,
    ) -> None:

        for node in result.graph.nodes:
            risk = node.event.risk_classification or RiskClassification()
            is_inflection_node = (
                result.inflection_node is not None
                and node.id == result.inflection_node.id
            )
            metadata_json = dict(node.event.metadata or {})
            metadata_json["lineage"] = {
                "summary": node.summary,
                "confidence": node.confidence,
                "evidence_refs": list(node.evidence_refs),
                "parent_ids": [str(parent_id) for parent_id in node.parent_ids],
                "primary_parent_id": str(node.primary_parent_id) if node.primary_parent_id else None,
                "lineage_ambiguities": list(node.lineage_ambiguities),
                "incoming_edges": [
                    edge.to_dict()
                    for edge in result.graph.incoming_edges(node.id)
                ],
            }
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
                metadata_json=metadata_json,
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
    lineage = metadata.get("lineage") if isinstance(metadata.get("lineage"), dict) else {}

    parent_refs: list[uuid.UUID] = []
    raw_parent_ids = lineage.get("parent_ids")
    if isinstance(raw_parent_ids, list):
        for parent_id in raw_parent_ids:
            if not isinstance(parent_id, str):
                continue
            try:
                parent_refs.append(uuid.UUID(parent_id))
            except ValueError:
                continue

    if node.parent_node_id is not None and node.parent_node_id not in parent_refs:
        parent_refs.insert(0, node.parent_node_id)

    return CanonicalEvent(
        id=node.id,
        session_id=str(session_id),
        timestamp=node.timestamp,
        ordinal=node.sequence_num,
        event_type=EventType(node.event_type),
        agent_id="",
        action=node.action,
        parent_event_id=node.parent_node_id,
        inputs=node.inputs,
        outputs=node.outputs,
        metadata=metadata,
        summary=lineage.get("summary") if isinstance(lineage.get("summary"), str) else None,
        parent_event_refs=parent_refs,
        ambiguities=[
            str(item)
            for item in lineage.get("lineage_ambiguities", [])
            if isinstance(item, str)
        ],
        risk_classification=RiskClassification(
            assumption_mutation=node.assumption_mutation,
            policy_divergence=node.policy_divergence,
            constraint_violation=node.constraint_violation,
            context_contamination=node.context_contamination,
            coverage_gap=node.coverage_gap,
            explanations=RiskClassification.explanations_from_dict(node.risk_explanations),
        ),
    )
