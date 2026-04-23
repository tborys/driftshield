import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import (
    ExplanationPayloadResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphResponse,
    PaginatedResponse,
    RecurrenceStatusResponse,
    SessionDetail,
    SessionExplanationItemResponse,
    SessionExplanationsResponse,
    SessionProvenanceResponse,
    SessionSummary,
    SignatureMatchSummaryResponse,
    ValidationCreateRequest,
    ValidationResponse,
)
from driftshield.core.models import RiskClassification
from driftshield.db.models import (
    DecisionNodeModel,
    SessionModel,
)
from driftshield.db.persistence import PersistenceService
from driftshield.db.validation_service import ValidationService

router = APIRouter()


def _count_risks(nodes: list[DecisionNodeModel]) -> int:
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


def _risk_summary(nodes: list[DecisionNodeModel]) -> dict[str, int]:
    summary = {flag_name: 0 for flag_name in RiskClassification.FLAG_FIELDS}
    for node in nodes:
        for flag_name in RiskClassification.FLAG_FIELDS:
            if getattr(node, flag_name):
                summary[flag_name] += 1
    return summary


def _risk_flags_for_node(node: DecisionNodeModel) -> list[str]:
    flags = []
    if node.assumption_mutation:
        flags.append("assumption_mutation")
    if node.policy_divergence:
        flags.append("policy_divergence")
    if node.constraint_violation:
        flags.append("constraint_violation")
    if node.context_contamination:
        flags.append("context_contamination")
    if node.coverage_gap:
        flags.append("coverage_gap")
    return flags


def _explanation_payload(payload: dict | None) -> ExplanationPayloadResponse | None:
    if payload is None:
        return None
    return ExplanationPayloadResponse(**payload)


def _risk_explanations_for_node(node: DecisionNodeModel) -> dict[str, ExplanationPayloadResponse]:
    payload = node.risk_explanations or {}
    return {
        flag_name: ExplanationPayloadResponse(**explanation)
        for flag_name, explanation in payload.items()
    }


def _session_provenance(session: SessionModel) -> SessionProvenanceResponse | None:
    if not any(
        [
            session.source_session_id,
            session.source_path,
            session.parser_version,
            session.ingested_at,
        ]
    ):
        return None
    source_type = None
    if session.parser_version:
        source_type = session.parser_version.split("@", 1)[0]
    return SessionProvenanceResponse(
        source_type=source_type,
        source_session_id=session.source_session_id,
        source_path=session.source_path,
        parser_version=session.parser_version,
        ingested_at=session.ingested_at,
    )


def _session_explanations(nodes: list[DecisionNodeModel]) -> SessionExplanationsResponse:
    risk_explanations: dict[str, list[SessionExplanationItemResponse]] = {}
    inflection_explanation: SessionExplanationItemResponse | None = None

    for node in nodes:
        for flag_name, explanation in _risk_explanations_for_node(node).items():
            risk_explanations.setdefault(flag_name, []).append(
                SessionExplanationItemResponse(node_id=node.id, payload=explanation)
            )
        if node.is_inflection_node and node.inflection_explanation is not None:
            inflection_explanation = SessionExplanationItemResponse(
                node_id=node.id,
                payload=ExplanationPayloadResponse(**node.inflection_explanation),
            )

    return SessionExplanationsResponse(
        risk_explanations=risk_explanations,
        inflection_explanation=inflection_explanation,
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _extract_signature_match(session: SessionModel) -> SignatureMatchSummaryResponse | None:
    metadata = session.metadata_json or {}
    payload = metadata.get("signature_match") or metadata.get("signature_summary")
    if not isinstance(payload, dict):
        return None

    matched_family_ids = payload.get("matched_family_ids")
    if not isinstance(matched_family_ids, list):
        matched_family_ids = []

    status = payload.get("status")
    if not isinstance(status, str):
        status = payload.get("outcome_status") if isinstance(payload.get("outcome_status"), str) else None

    return SignatureMatchSummaryResponse(
        status=status,
        primary_family_id=(
            payload.get("primary_family_id")
            if isinstance(payload.get("primary_family_id"), str)
            else None
        ),
        matched_family_ids=[item for item in matched_family_ids if isinstance(item, str)],
        match_count=_optional_int(payload.get("match_count")),
        summary=payload.get("summary") if isinstance(payload.get("summary"), str) else None,
        raw=payload,
    )


def _extract_recurrence_status(session: SessionModel) -> RecurrenceStatusResponse | None:
    metadata = session.metadata_json or {}
    payload = metadata.get("recurrence_status")
    if not isinstance(payload, dict):
        return None

    return RecurrenceStatusResponse(
        status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        cluster_id=payload.get("cluster_id") if isinstance(payload.get("cluster_id"), str) else None,
        recurrence_count=_optional_int(payload.get("recurrence_count")),
        summary=payload.get("summary") if isinstance(payload.get("summary"), str) else None,
        raw=payload,
    )


@router.get("/api/sessions")
def list_sessions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    flagged_only: bool = Query(default=False),
    risk_class: str | None = Query(default=None),
    source: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    service = PersistenceService(db)
    try:
        sessions, total = service.list_sessions(
            page=page,
            per_page=per_page,
            flagged_only=flagged_only,
            risk_class=risk_class,
            source=source,
            since_hours=since_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    pages = math.ceil(total / per_page) if total > 0 else 0

    items = []
    for session in sessions:
        nodes = db.query(DecisionNodeModel).filter(
            DecisionNodeModel.session_id == session.id
        ).all()
        risk_count = _count_risks(nodes)
        has_inflection = any(node.is_inflection_node for node in nodes)
        items.append(
            SessionSummary(
                id=session.id,
                agent_id=session.agent_id,
                external_id=session.external_id,
                status=session.status,
                started_at=session.started_at,
                ended_at=session.ended_at,
                risk_flag_count=risk_count,
                has_inflection=has_inflection,
                provenance=_session_provenance(session),
            )
        )

    return PaginatedResponse(
        items=[item.model_dump(mode="json") for item in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get("/api/sessions/{session_id}")
def get_session(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    nodes = db.query(DecisionNodeModel).filter(
        DecisionNodeModel.session_id == session_id
    ).order_by(DecisionNodeModel.sequence_num).all()
    risk_count = _count_risks(nodes)

    return SessionDetail(
        id=session.id,
        agent_id=session.agent_id,
        external_id=session.external_id,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        risk_flag_count=risk_count,
        has_inflection=any(node.is_inflection_node for node in nodes),
        provenance=_session_provenance(session),
        total_events=len(nodes),
        flagged_events=risk_count,
        risk_summary=_risk_summary(nodes),
        explanations=_session_explanations(nodes),
        signature_match=_extract_signature_match(session),
        recurrence_status=_extract_recurrence_status(session),
    )


@router.get("/api/sessions/{session_id}/graph")
def get_session_graph(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    node_models = (
        db.query(DecisionNodeModel)
        .filter(DecisionNodeModel.session_id == session_id)
        .order_by(DecisionNodeModel.sequence_num)
        .all()
    )
    if not node_models:
        raise HTTPException(status_code=404, detail="No graph data for session")

    graph = PersistenceService(db).load_graph(session_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No graph data for session")

    node_models_by_id = {node.id: node for node in node_models}
    graph_nodes = []
    for graph_node in graph.nodes:
        node = node_models_by_id[graph_node.id]
        graph_nodes.append(
            GraphNodeResponse(
                id=graph_node.id,
                node_kind=graph_node.node_kind,
                event_type=node.event_type,
                action=node.action,
                summary=graph_node.summary,
                confidence=graph_node.confidence,
                sequence_num=graph_node.sequence_num,
                risk_flags=_risk_flags_for_node(node),
                risk_explanations=_risk_explanations_for_node(node),
                evidence_refs=list(graph_node.evidence_refs),
                is_inflection=node.is_inflection_node,
                inflection_explanation=_explanation_payload(node.inflection_explanation),
                inputs=node.inputs,
                outputs=node.outputs,
                metadata=node.metadata_json,
                parent_node_id=graph_node.primary_parent_id,
                parent_node_ids=list(graph_node.parent_ids),
                lineage_ambiguities=list(graph_node.lineage_ambiguities),
            )
        )

    edges = [
        GraphEdgeResponse(
            source=edge.source_id,
            target=edge.target_id,
            relationship=edge.relationship,
            confidence=edge.confidence,
            inferred=edge.inferred,
            reason=edge.reason,
            evidence_refs=list(edge.evidence_refs),
        )
        for edge in graph.edges
    ]

    return GraphResponse(
        session_id=session_id,
        provenance=_session_provenance(session),
        nodes=graph_nodes,
        edges=edges,
    )


@router.get("/api/sessions/{session_id}/validations")
def list_session_validations(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = ValidationService(db)
    rows = service.list_validations(session_id=session_id)
    return [
        ValidationResponse(
            id=row.id,
            session_id=row.session_id,
            target_type=row.target_type,
            target_ref=row.target_ref,
            verdict=row.verdict,
            confidence=row.confidence,
            reviewer=row.reviewer,
            notes=row.notes,
            metadata_json=row.metadata_json,
            shareable=row.shareable,
            created_at=row.created_at,
        ).model_dump(mode="json")
        for row in rows
    ]


@router.post("/api/sessions/{session_id}/validations")
def create_session_validation(
    session_id: uuid.UUID,
    payload: ValidationCreateRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = ValidationService(db)
    try:
        row = service._record(
            session_id=session_id,
            target_type=payload.target_type,
            target_ref=payload.target_ref,
            verdict=payload.verdict,
            reviewer=payload.reviewer,
            confidence=payload.confidence,
            notes=payload.notes,
            metadata_json=payload.metadata_json,
            shareable=payload.shareable,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created = ValidationResponse(
        id=row.id,
        session_id=row.session_id,
        target_type=row.target_type,
        target_ref=row.target_ref,
        verdict=row.verdict,
        confidence=row.confidence,
        reviewer=row.reviewer,
        notes=row.notes,
        metadata_json=row.metadata_json,
        shareable=row.shareable,
        created_at=row.created_at,
    )
    return created.model_dump(mode="json")
