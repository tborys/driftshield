import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DBSession

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode, LineageGraph
from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    ForensicArtifactRef,
    ForensicCase,
    ForensicCaseState,
    RiskClassification,
    Session as DomainSession,
    SessionStatus,
)
from driftshield.db.models import (
    DecisionNodeModel,
    ForensicCaseModel,
    ReportModel,
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
        self.upsert_forensic_case(session, result)
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
        self.upsert_forensic_case(session, result)
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
            metadata_json["normalized_event"] = _normalized_event_payload(node.event)
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
            external_id=model.external_id,
            ended_at=model.ended_at,
            status=SessionStatus(model.status),
            metadata=dict(model.metadata_json or {}),
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

    def load_case(self, case_id: uuid.UUID) -> ForensicCase | None:
        model = self._db.get(ForensicCaseModel, case_id)
        if model is None:
            return None
        return _case_model_to_domain(model)

    def load_case_for_session(self, session_id: uuid.UUID) -> ForensicCase | None:
        model = (
            self._db.query(ForensicCaseModel)
            .filter(ForensicCaseModel.session_id == session_id)
            .one_or_none()
        )
        if model is None:
            return None
        return _case_model_to_domain(model)

    def upsert_forensic_case(
        self,
        session: DomainSession,
        result: AnalysisResult,
        *,
        report: ReportModel | None = None,
    ) -> ForensicCase:
        now = datetime.now(timezone.utc)
        model = (
            self._db.query(ForensicCaseModel)
            .filter(ForensicCaseModel.session_id == session.id)
            .one_or_none()
        )
        if model is None:
            model = ForensicCaseModel(
                id=uuid.uuid4(),
                session_id=session.id,
                report_id=None,
                state=ForensicCaseState.DRAFT.value,
                artifact_refs=[],
                review_refs=[],
                audit_refs=[],
                created_at=now,
                updated_at=now,
            )
            self._db.add(model)

        model.report_id = report.id if report is not None else None
        model.state = (
            ForensicCaseState.REPORTED.value if report is not None else ForensicCaseState.DRAFT.value
        )
        model.artifact_refs = [
            ref.to_dict()
            for ref in _build_forensic_case_artifact_refs(session, result, report=report)
        ]
        model.review_refs = list(model.review_refs or [])
        model.audit_refs = list(model.audit_refs or [])
        model.updated_at = now
        self._db.flush()
        return _case_model_to_domain(model)

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
    normalized_event = (
        metadata.get("normalized_event")
        if isinstance(metadata.get("normalized_event"), dict)
        else {}
    )

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

    ambiguities = [
        str(item)
        for item in lineage.get("lineage_ambiguities", [])
        if isinstance(item, str)
    ]
    for item in normalized_event.get("ambiguities", []):
        if isinstance(item, str) and item not in ambiguities:
            ambiguities.append(item)

    return CanonicalEvent(
        id=node.id,
        session_id=str(session_id),
        timestamp=node.timestamp,
        ordinal=(
            normalized_event.get("ordinal")
            if isinstance(normalized_event.get("ordinal"), int)
            else node.sequence_num
        ),
        event_type=EventType(node.event_type),
        agent_id="",
        action=node.action,
        parent_event_id=node.parent_node_id,
        inputs=node.inputs,
        outputs=node.outputs,
        metadata=metadata,
        actor=(
            dict(normalized_event.get("actor"))
            if isinstance(normalized_event.get("actor"), dict)
            else None
        ),
        summary=(
            lineage.get("summary")
            if isinstance(lineage.get("summary"), str)
            else normalized_event.get("summary")
            if isinstance(normalized_event.get("summary"), str)
            else None
        ),
        parent_event_refs=parent_refs,
        source_refs=_normalized_event_refs(normalized_event.get("source_refs")),
        artifact_refs=_normalized_event_refs(normalized_event.get("artifact_refs")),
        constraints=_normalized_event_refs(normalized_event.get("constraints")),
        tool_activity=(
            dict(normalized_event.get("tool_activity"))
            if isinstance(normalized_event.get("tool_activity"), dict)
            else None
        ),
        failure_context=(
            dict(normalized_event.get("failure_context"))
            if isinstance(normalized_event.get("failure_context"), dict)
            else None
        ),
        ambiguities=ambiguities,
        risk_classification=RiskClassification(
            assumption_mutation=node.assumption_mutation,
            policy_divergence=node.policy_divergence,
            constraint_violation=node.constraint_violation,
            context_contamination=node.context_contamination,
            coverage_gap=node.coverage_gap,
            explanations=RiskClassification.explanations_from_dict(node.risk_explanations),
        ),
    )


def _normalized_event_payload(event: CanonicalEvent) -> dict[str, object]:
    return {
        "ordinal": event.ordinal,
        "actor": dict(event.actor or {}),
        "summary": event.summary,
        "source_refs": [dict(ref) for ref in event.source_refs],
        "artifact_refs": [dict(ref) for ref in event.artifact_refs],
        "constraints": [dict(ref) for ref in event.constraints],
        "tool_activity": dict(event.tool_activity or {}) if event.tool_activity else None,
        "failure_context": dict(event.failure_context or {}) if event.failure_context else None,
        "ambiguities": list(event.ambiguities),
    }


def _normalized_event_refs(payload: object) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if not isinstance(payload, list):
        return refs

    for item in payload:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                str(key): str(value)
                for key, value in item.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    return refs


def _build_forensic_case_artifact_refs(
    session: DomainSession,
    result: AnalysisResult,
    *,
    report: ReportModel | None = None,
) -> list[ForensicArtifactRef]:
    refs = [
        ForensicArtifactRef(
            ref_id=f"session:{session.id}",
            kind="analysis_session",
            role="session",
            target_ref=str(session.id),
            summary=f"{session.status.value} run for {session.agent_id}",
            metadata={
                "agent_id": session.agent_id,
                "status": session.status.value,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            },
        ),
        ForensicArtifactRef(
            ref_id=f"lineage:{session.id}",
            kind="lineage_graph",
            role="lineage",
            target_ref=str(session.id),
            summary=f"{len(result.graph.nodes)} nodes and {len(result.graph.edges)} edges",
            metadata={
                "node_count": len(result.graph.nodes),
                "edge_count": len(result.graph.edges),
                "flagged_events": result.flagged_events,
                "inflection_node_id": (
                    str(result.inflection_node.id) if result.inflection_node is not None else None
                ),
            },
        ),
    ]

    included_node_refs = 0
    for node in result.graph.nodes:
        if _include_forensic_case_node(node):
            included_node_refs += 1
            refs.append(
                ForensicArtifactRef(
                    ref_id=f"decision_node:{node.id}",
                    kind="decision_node",
                    role="evidence_node",
                    target_ref=str(node.id),
                    summary=node.summary,
                    evidence_refs=list(node.evidence_refs),
                    metadata={
                        "sequence_num": node.sequence_num,
                        "event_type": node.event_type.value,
                        "action": node.action,
                        "confidence": node.confidence,
                        "parent_node_ids": [str(parent_id) for parent_id in node.parent_ids],
                        "lineage_ambiguities": list(node.lineage_ambiguities),
                        "risk_flags": _active_risk_flags(node.event.risk_classification),
                        "is_inflection": node.is_inflection_node,
                        "failure_context": (
                            dict(node.event.failure_context)
                            if node.event.failure_context
                            else None
                        ),
                        "source_refs": [dict(ref) for ref in node.event.source_refs],
                    },
                )
            )

        for index, artifact in enumerate(node.event.artifact_refs):
            refs.append(
                ForensicArtifactRef(
                    ref_id=f"decision_node:{node.id}:artifact:{index}",
                    kind="artifact",
                    role="event_artifact",
                    target_ref=str(node.id),
                    summary=_artifact_summary(artifact),
                    evidence_refs=[f"artifact_refs[{index}]"],
                    metadata=dict(artifact),
                )
            )

    if included_node_refs == 0 and result.graph.nodes:
        first_node = result.graph.nodes[0]
        refs.append(
            ForensicArtifactRef(
                ref_id=f"decision_node:{first_node.id}",
                kind="decision_node",
                role="lineage_node",
                target_ref=str(first_node.id),
                summary=first_node.summary,
                evidence_refs=list(first_node.evidence_refs),
                metadata={
                    "sequence_num": first_node.sequence_num,
                    "event_type": first_node.event_type.value,
                    "action": first_node.action,
                    "confidence": first_node.confidence,
                    "parent_node_ids": [str(parent_id) for parent_id in first_node.parent_ids],
                    "lineage_ambiguities": list(first_node.lineage_ambiguities),
                    "risk_flags": _active_risk_flags(first_node.event.risk_classification),
                    "is_inflection": first_node.is_inflection_node,
                    "failure_context": (
                        dict(first_node.event.failure_context)
                        if first_node.event.failure_context
                        else None
                    ),
                    "source_refs": [dict(ref) for ref in first_node.event.source_refs],
                },
            )
        )

    if report is not None:
        refs.append(
            ForensicArtifactRef(
                ref_id=f"report:{report.id}",
                kind="report",
                role="report_artifact",
                target_ref=str(report.id),
                summary=f"{report.report_type} report",
                metadata={
                    "report_type": report.report_type,
                    "generated_at": report.generated_at.isoformat(),
                    "generated_by": report.generated_by,
                },
            )
        )

    return refs


def _include_forensic_case_node(node: DecisionNode) -> bool:
    return bool(
        node.evidence_refs
        or node.lineage_ambiguities
        or node.is_inflection_node
        or node.has_risk_flags()
        or node.event.failure_context
        or node.event.artifact_refs
    )


def _active_risk_flags(risk: RiskClassification | None) -> list[str]:
    if risk is None:
        return []
    return risk.active_flags()


def _artifact_summary(artifact: dict[str, str]) -> str | None:
    kind = artifact.get("kind")
    value = artifact.get("value")
    if kind and value:
        return f"{kind}: {value}"
    if value:
        return value
    if kind:
        return kind
    return None


def _case_model_to_domain(model: ForensicCaseModel) -> ForensicCase:
    return ForensicCase(
        id=model.id,
        session_id=model.session_id,
        state=ForensicCaseState(model.state),
        report_id=model.report_id,
        artifact_refs=[
            artifact
            for artifact in (
                ForensicArtifactRef.from_dict(payload)
                for payload in (model.artifact_refs or [])
            )
            if artifact is not None
        ],
        review_refs=[str(ref) for ref in (model.review_refs or []) if isinstance(ref, str)],
        audit_refs=[str(ref) for ref in (model.audit_refs or []) if isinstance(ref, str)],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
