import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import (
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphResponse,
    PaginatedResponse,
    SessionDetail,
    SessionSummary,
    ValidationCreateRequest,
    ValidationResponse,
)
from driftshield.db.models import DecisionNodeModel, SessionModel
from driftshield.db.persistence import PersistenceService
from driftshield.db.validation_service import ValidationService

router = APIRouter()


def _count_risks(nodes: list[DecisionNodeModel]) -> int:
    return sum(
        1 for n in nodes if any([
            n.assumption_mutation, n.policy_divergence, n.constraint_violation,
            n.context_contamination, n.coverage_gap,
        ])
    )


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
    for s in sessions:
        nodes = db.query(DecisionNodeModel).filter(
            DecisionNodeModel.session_id == s.id
        ).all()
        risk_count = _count_risks(nodes)
        has_inflection = any(n.is_inflection_node for n in nodes)
        items.append(SessionSummary(
            id=s.id,
            agent_id=s.agent_id,
            external_id=s.external_id,
            status=s.status,
            started_at=s.started_at,
            ended_at=s.ended_at,
            risk_flag_count=risk_count,
            has_inflection=has_inflection,
        ))

    return PaginatedResponse(
        items=[i.model_dump(mode="json") for i in items],
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

    return SessionDetail(
        id=session.id,
        agent_id=session.agent_id,
        external_id=session.external_id,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        risk_flag_count=risk_count,
        has_inflection=any(n.is_inflection_node for n in nodes),
        total_events=len(nodes),
        flagged_events=risk_count,
    )


def _risk_flags_for_node(n: DecisionNodeModel) -> list[str]:
    flags = []
    if n.assumption_mutation:
        flags.append("assumption_mutation")
    if n.policy_divergence:
        flags.append("policy_divergence")
    if n.constraint_violation:
        flags.append("constraint_violation")
    if n.context_contamination:
        flags.append("context_contamination")
    if n.coverage_gap:
        flags.append("coverage_gap")
    return flags


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
    for n in nodes:
        graph_nodes.append(GraphNodeResponse(
            id=n.id,
            event_type=n.event_type,
            action=n.action,
            sequence_num=n.sequence_num,
            risk_flags=_risk_flags_for_node(n),
            is_inflection=n.is_inflection_node,
            inputs=n.inputs,
            outputs=n.outputs,
            metadata=n.metadata_json,
            parent_node_id=n.parent_node_id,
        ))

        if n.parent_node_id is not None:
            edges.append(GraphEdgeResponse(source=n.parent_node_id, target=n.id))

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
            id=r.id,
            session_id=r.session_id,
            target_type=r.target_type,
            target_ref=r.target_ref,
            verdict=r.verdict,
            confidence=r.confidence,
            reviewer=r.reviewer,
            notes=r.notes,
            metadata_json=r.metadata_json,
            shareable=r.shareable,
            created_at=r.created_at,
        ).model_dump(mode="json")
        for r in rows
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
