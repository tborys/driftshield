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
    SessionDetail,
    SessionSummary,
    ValidationCreateRequest,
    ValidationResponse,
)
from driftshield.db.models import (
    DecisionNodeModel,
    RecurrenceSignatureModel,
    SessionModel,
    SessionSignatureModel,
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


def _recurrence_summary(db: DBSession, session_id: uuid.UUID) -> tuple[str | None, str | None, int | None]:
    link = db.query(SessionSignatureModel).filter(
        SessionSignatureModel.session_id == session_id
    ).first()
    if link is None:
        return None, None, None

    sig = db.get(RecurrenceSignatureModel, link.signature_id)
    if sig is None:
        return None, None, None

    level = None
    probability = None
    if isinstance(sig.pattern, dict):
        level = sig.pattern.get("level")
        probability = sig.pattern.get("probability")

    return level, probability or sig.severity, sig.occurrence_count


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


@router.get("/api/sessions")
def list_sessions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    service = PersistenceService(db)
    sessions, total = service.list_sessions(page=page, per_page=per_page)
    pages = math.ceil(total / per_page) if total > 0 else 0

    items = []
    for session in sessions:
        nodes = db.query(DecisionNodeModel).filter(
            DecisionNodeModel.session_id == session.id
        ).all()
        risk_count = _count_risks(nodes)
        has_inflection = any(node.is_inflection_node for node in nodes)
        recurrence_level, recurrence_probability, recurrence_count = _recurrence_summary(db, session.id)
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
                recurrence_level=recurrence_level,
                recurrence_probability=recurrence_probability,
                recurrence_count=recurrence_count,
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
    ).all()
    risk_count = _count_risks(nodes)
    recurrence_level, recurrence_probability, recurrence_count = _recurrence_summary(db, session_id)

    return SessionDetail(
        id=session.id,
        agent_id=session.agent_id,
        external_id=session.external_id,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        risk_flag_count=risk_count,
        has_inflection=any(node.is_inflection_node for node in nodes),
        recurrence_level=recurrence_level,
        recurrence_probability=recurrence_probability,
        recurrence_count=recurrence_count,
        total_events=len(nodes),
        flagged_events=risk_count,
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

    nodes = (
        db.query(DecisionNodeModel)
        .filter(DecisionNodeModel.session_id == session_id)
        .order_by(DecisionNodeModel.sequence_num)
        .all()
    )
    if not nodes:
        raise HTTPException(status_code=404, detail="No graph data for session")

    graph_nodes = []
    edges = []
    for node in nodes:
        graph_nodes.append(
            GraphNodeResponse(
                id=node.id,
                event_type=node.event_type,
                action=node.action,
                sequence_num=node.sequence_num,
                risk_flags=_risk_flags_for_node(node),
                risk_explanations=_risk_explanations_for_node(node),
                is_inflection=node.is_inflection_node,
                inflection_explanation=_explanation_payload(node.inflection_explanation),
                inputs=node.inputs,
                outputs=node.outputs,
                metadata=node.metadata_json,
                parent_node_id=node.parent_node_id,
            )
        )

        if node.parent_node_id is not None:
            edges.append(GraphEdgeResponse(source=node.parent_node_id, target=node.id))

    return GraphResponse(session_id=session_id, nodes=graph_nodes, edges=edges)


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
    row = service._record(
        session_id=session_id,
        target_type=payload.target_type,
        target_ref=payload.target_ref,
        verdict=payload.verdict,
        reviewer=payload.reviewer,
        confidence=payload.confidence,
        notes=payload.notes,
        metadata_json=None,
        shareable=payload.shareable,
    )
    db.commit()

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
