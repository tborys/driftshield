import math
import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import (
    ExplanationPayloadResponse,
    ForensicFeedbackCreateRequest,
    ForensicFeedbackResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphResponse,
    IntegrityStatusResponse,
    PaginatedResponse,
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
    AnalystValidationModel,
    DecisionNodeModel,
    ReportModel,
    SessionModel,
)
from driftshield.db.persistence import PersistenceService
from driftshield.db.validation_service import ValidationRecord, ValidationService

router = APIRouter()
_REPORT_BOUND_FEEDBACK_TARGET_KINDS = {
    "classification",
    "finding",
    "pattern_match",
    "candidate_break_point",
    "evidence_gap",
}


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


def _explanation_payload(payload: dict[str, object] | None) -> ExplanationPayloadResponse | None:
    if payload is None:
        return None
    return ExplanationPayloadResponse(**cast(dict[str, Any], payload))


def _risk_explanations_for_node(node: DecisionNodeModel) -> dict[str, ExplanationPayloadResponse]:
    payload = node.risk_explanations or {}
    return {
        flag_name: ExplanationPayloadResponse(**explanation)
        for flag_name, explanation in payload.items()
    }


def _session_provenance(session: SessionModel) -> SessionProvenanceResponse | None:
    metadata = session.metadata_json or {}
    integrity_provenance = metadata.get("integrity_provenance")
    if isinstance(integrity_provenance, dict):
        return SessionProvenanceResponse(**integrity_provenance)

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
        transcript_hash=session.transcript_hash,
        ingested_at=session.ingested_at,
    )


def _extract_integrity_status(session: SessionModel) -> IntegrityStatusResponse | None:
    metadata = session.metadata_json or {}
    payload = metadata.get("integrity_summary")
    if not isinstance(payload, dict):
        return None
    return IntegrityStatusResponse(**payload)


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

    matched_mechanism_ids = payload.get("matched_mechanism_ids")
    if not isinstance(matched_mechanism_ids, list):
        matched_mechanism_ids = payload.get("matched_family_ids")
    if not isinstance(matched_mechanism_ids, list):
        matched_mechanism_ids = []

    status = payload.get("status")
    if not isinstance(status, str):
        status = payload.get("outcome_status") if isinstance(payload.get("outcome_status"), str) else None

    primary_mechanism_id = payload.get("primary_mechanism_id")
    if not isinstance(primary_mechanism_id, str):
        primary_mechanism_id = (
            payload.get("primary_family_id")
            if isinstance(payload.get("primary_family_id"), str)
            else None
        )

    summary = payload.get("summary") if isinstance(payload.get("summary"), str) else None
    if summary is not None and "OSS-safe signals" not in summary:
        rewritten = summary.replace("failure families", "failure mechanisms").replace(
            "failure family", "failure mechanism"
        )
        if rewritten.startswith("Matched ") and rewritten.endswith("."):
            summary = rewritten[:-1] + " from local OSS-safe signals."
        else:
            summary = rewritten

    return SignatureMatchSummaryResponse(
        status=status,
        primary_mechanism_id=primary_mechanism_id,
        matched_mechanism_ids=[item for item in matched_mechanism_ids if isinstance(item, str)],
        match_count=_optional_int(payload.get("match_count")),
        summary=summary,
        raw=payload,
    )


def _feedback_response(
    row: ValidationRecord | AnalystValidationModel,
) -> ForensicFeedbackResponse:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    feedback = metadata.get("forensic_feedback") if isinstance(metadata, dict) else None
    if not isinstance(feedback, dict):
        feedback = {}

    report_id = None
    if isinstance(feedback.get("report_id"), str):
        try:
            report_id = uuid.UUID(feedback["report_id"])
        except ValueError:
            report_id = None

    return ForensicFeedbackResponse(
        id=row.id,
        session_id=row.session_id,
        target_kind=str(feedback.get("target_kind") or ""),
        target_ref=row.target_ref,
        category=str(feedback.get("category") or ""),
        outcome=str(feedback.get("outcome") or ""),
        verdict=row.verdict,
        reviewer=row.reviewer,
        report_id=report_id,
        confidence=row.confidence,
        notes=row.notes,
        suggested_failure_family=(
            feedback.get("suggested_failure_family")
            if isinstance(feedback.get("suggested_failure_family"), str)
            else None
        ),
        problem_detail=(
            feedback.get("problem_detail")
            if isinstance(feedback.get("problem_detail"), str)
            else None
        ),
        shareable=row.shareable,
        created_at=row.created_at,
    )


def _load_report_for_feedback(
    *,
    session_id: uuid.UUID,
    payload: ForensicFeedbackCreateRequest,
    db: DBSession,
) -> ReportModel | None:
    report_id = payload.report_id
    if payload.target_kind == "report":
        try:
            target_report_id = uuid.UUID(payload.target_ref)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="target_ref must be a report UUID when target_kind is report",
            ) from exc
        if report_id is not None and report_id != target_report_id:
            raise HTTPException(status_code=422, detail="report_id must match report target_ref")
        report_id = target_report_id

    if report_id is None and payload.target_kind in _REPORT_BOUND_FEEDBACK_TARGET_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"report_id is required for {payload.target_kind} feedback",
        )

    if report_id is None:
        return None

    report = db.get(ReportModel, report_id)
    if report is None or report.session_id != session_id:
        raise HTTPException(status_code=404, detail="Report not found for session")

    _validate_report_feedback_target(report, payload)
    return report


def _validate_report_feedback_target(
    report: ReportModel,
    payload: ForensicFeedbackCreateRequest,
) -> None:
    content = report.content_json if isinstance(report.content_json, dict) else {}
    if payload.target_kind == "finding":
        findings = content.get("findings") if isinstance(content, dict) else None
        if not _contains_ref(findings, "finding_id", payload.target_ref):
            raise HTTPException(status_code=422, detail="Finding target_ref not found in report")
    elif payload.target_kind == "evidence_gap":
        findings = content.get("findings") if isinstance(content, dict) else None
        if not _contains_finding_kind(findings, payload.target_ref, "evidence_gap"):
            raise HTTPException(status_code=422, detail="Evidence gap target_ref not found in report")
    elif payload.target_kind == "pattern_match":
        matches = content.get("pattern_matches") if isinstance(content, dict) else None
        if not _contains_ref(matches, "match_id", payload.target_ref):
            raise HTTPException(status_code=422, detail="Pattern match target_ref not found in report")
    elif payload.target_kind == "candidate_break_point":
        if not isinstance(content.get("candidate_break_point"), dict):
            raise HTTPException(status_code=422, detail="Report has no candidate break point target")
    elif payload.target_kind == "classification":
        if not isinstance(content.get("classification"), str):
            raise HTTPException(status_code=422, detail="Report has no classification target")


def _contains_ref(items: object, key: str, value: str) -> bool:
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get(key) == value for item in items)


def _contains_finding_kind(items: object, finding_id: str, finding_kind: str) -> bool:
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("finding_id") == finding_id
        and item.get("finding_kind") == finding_kind
        for item in items
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
) -> PaginatedResponse:
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
                integrity_status=_extract_integrity_status(session),
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
) -> SessionDetail:
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
        integrity_status=_extract_integrity_status(session),
        total_events=len(nodes),
        flagged_events=risk_count,
        risk_summary=_risk_summary(nodes),
        explanations=_session_explanations(nodes),
        signature_match=_extract_signature_match(session),
    )


@router.get("/api/sessions/{session_id}/graph")
def get_session_graph(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> GraphResponse:
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
) -> list[dict[str, object]]:
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
) -> dict[str, object]:
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


@router.get("/api/sessions/{session_id}/forensic-feedback")
def list_session_forensic_feedback(
    session_id: uuid.UUID,
    report_id: uuid.UUID | None = Query(default=None),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> list[dict[str, object]]:
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if report_id is not None:
        report = db.get(ReportModel, report_id)
        if report is None or report.session_id != session_id:
            raise HTTPException(status_code=404, detail="Report not found for session")

    rows = ValidationService(db).list_forensic_feedback(
        session_id=session_id,
        report_id=report_id,
    )
    return [_feedback_response(row).model_dump(mode="json") for row in rows]


@router.post("/api/sessions/{session_id}/forensic-feedback", status_code=201)
def create_session_forensic_feedback(
    session_id: uuid.UUID,
    payload: ForensicFeedbackCreateRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    report = _load_report_for_feedback(session_id=session_id, payload=payload, db=db)

    service = ValidationService(db)
    try:
        row = service.record_forensic_feedback(
            session_id=session_id,
            target_kind=payload.target_kind,
            target_ref=payload.target_ref,
            category=payload.category,
            outcome=payload.outcome,
            reviewer=payload.reviewer,
            report_id=report.id if report is not None else payload.report_id,
            confidence=payload.confidence,
            notes=payload.notes,
            suggested_failure_family=payload.suggested_failure_family,
            problem_detail=payload.problem_detail,
            shareable=payload.shareable,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _feedback_response(row).model_dump(mode="json")
