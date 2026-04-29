import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.ingest_workflow import (
    ingest_transcript_bytes,
    read_upload_bytes,
    record_analysis_telemetry,
)
from driftshield.api.schemas import (
    ForensicCaseResponse,
    ForensicWorkflowResponse,
    GeneratedReportResponse,
)
from driftshield.core.analysis.inflection import select_inflection_node
from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import ForensicCase
from driftshield.db.models import ReportModel, SessionModel
from driftshield.db.persistence import PersistenceService
from driftshield.reports.builder import ReportBuilder
from driftshield.reports.json_export import export_json
from driftshield.reports.markdown import render_markdown
from driftshield.reports.models import ReportType

router = APIRouter()


class GenerateReportRequest(BaseModel):
    report_type: str = "full"


@router.post("/api/sessions/{session_id}/report", status_code=201)
def generate_report(
    session_id: uuid.UUID,
    request: GenerateReportRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    del api_key
    session_model = db.get(SessionModel, session_id)
    if session_model is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = PersistenceService(db)
    domain_session = service.load_session(session_id)
    graph = service.load_graph(session_id)

    if domain_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if graph is None:
        raise HTTPException(status_code=404, detail="No graph data for session")

    selection = select_inflection_node(graph, graph.nodes[-1].id) if graph.nodes else None
    events = [node.event for node in graph.nodes]
    flagged = sum(
        1 for event in events if event.risk_classification and event.risk_classification.has_any_flag()
    )
    result = AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=selection.node if selection is not None else None,
        total_events=len(events),
        flagged_events=flagged,
        inflection_explanation=selection.explanation if selection is not None else None,
        candidate_break_point=(
            selection.candidate_break_point if selection is not None else None
        ),
    )

    report_type = _parse_report_type(request.report_type)
    metadata = session_model.metadata_json or {}
    integrity_snapshot = None
    if isinstance(metadata.get("integrity_summary"), dict):
        integrity_snapshot = {
            "summary": metadata.get("integrity_summary"),
            "provenance": metadata.get("integrity_provenance"),
        }

    report_data = ReportBuilder().build(
        domain_session,
        result,
        report_type=report_type,
        integrity_snapshot=integrity_snapshot,
    )
    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=report_data.generated_at,
        report_type=report_type.value,
        content_markdown=render_markdown(report_data),
        content_json=export_json(report_data),
        generated_by="system",
    )
    db.add(report)
    db.flush()
    service.upsert_forensic_case(domain_session, result, report=report)
    return {"id": report.id, "report_type": report.report_type}


@router.post("/api/forensics/report", response_model=ForensicWorkflowResponse, status_code=201)
def generate_forensic_report(
    response: Response,
    file: UploadFile = File(...),
    format: str = Form(default="auto"),
    report_type: str = Form(default="full"),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> ForensicWorkflowResponse:
    del api_key
    requested_report_type = _parse_report_type(report_type)
    raw_bytes = read_upload_bytes(file)

    try:
        outcome, analysis_result, parser_name = ingest_transcript_bytes(
            db,
            raw_bytes=raw_bytes,
            format_name=format,
            filename=file.filename,
            commit=False,
        )

        if outcome.deduplicated:
            existing_report = _load_existing_report_for_case(
                session_id=outcome.session_id,
                report_type=requested_report_type,
                db=db,
            )
            if existing_report is not None:
                report, forensic_case = existing_report
                response.status_code = 200
                return ForensicWorkflowResponse(
                    session_id=outcome.session_id,
                    ingest_status=outcome.status,
                    deduplicated=outcome.deduplicated,
                    parser_name=parser_name,
                    source_path=file.filename,
                    report=_report_response(report),
                    forensic_case=_forensic_case_response(forensic_case),
                )

        report, forensic_case = _create_report_for_session(
            session_id=outcome.session_id,
            report_type=requested_report_type,
            db=db,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not outcome.deduplicated and analysis_result is not None:
        record_analysis_telemetry(analysis_result)

    return ForensicWorkflowResponse(
        session_id=outcome.session_id,
        ingest_status=outcome.status,
        deduplicated=outcome.deduplicated,
        parser_name=parser_name,
        source_path=file.filename,
        report=_report_response(report),
        forensic_case=_forensic_case_response(forensic_case),
    )


@router.get("/api/sessions/{session_id}/reports")
def list_session_reports(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> list[dict[str, object]]:
    reports = (
        db.query(ReportModel)
        .filter(ReportModel.session_id == session_id)
        .order_by(ReportModel.generated_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "report_type": r.report_type,
            "generated_at": r.generated_at.isoformat(),
            "generated_by": r.generated_by,
        }
        for r in reports
    ]


@router.get("/api/reports/{report_id}")
def get_report(
    report_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    report = db.get(ReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "id": report.id,
        "session_id": report.session_id,
        "report_type": report.report_type,
        "generated_at": report.generated_at.isoformat(),
        "content_markdown": report.content_markdown,
        "content_json": report.content_json,
        "generated_by": report.generated_by,
    }


def _create_report_for_session(
    *,
    session_id: uuid.UUID,
    report_type: ReportType,
    db: DBSession,
) -> tuple[ReportModel, ForensicCase]:
    service = PersistenceService(db)
    domain_session = service.load_session(session_id)
    if domain_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    graph = service.load_graph(session_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No graph data for session")

    result = _analysis_result_from_graph(graph)
    report_data = ReportBuilder().build(domain_session, result, report_type=report_type)

    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=report_data.generated_at,
        report_type=report_type.value,
        content_markdown=render_markdown(report_data),
        content_json=export_json(report_data),
        generated_by="system",
    )
    db.add(report)
    db.flush()
    forensic_case = service.upsert_forensic_case(domain_session, result, report=report)
    return report, forensic_case


def _load_existing_report_for_case(
    *,
    session_id: uuid.UUID,
    report_type: ReportType,
    db: DBSession,
) -> tuple[ReportModel, ForensicCase] | None:
    service = PersistenceService(db)
    forensic_case = service.load_case_for_session(session_id)
    if forensic_case is None or forensic_case.report_id is None:
        return None

    report = db.get(ReportModel, forensic_case.report_id)
    if report is None or report.report_type != report_type.value:
        return None

    return report, forensic_case


def _analysis_result_from_graph(graph: LineageGraph) -> AnalysisResult:
    selection = select_inflection_node(graph, graph.nodes[-1].id) if graph.nodes else None
    events = [node.event for node in graph.nodes]
    flagged = sum(
        1 for event in events if event.risk_classification and event.risk_classification.has_any_flag()
    )
    return AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=selection.node if selection is not None else None,
        total_events=len(events),
        flagged_events=flagged,
        inflection_explanation=selection.explanation if selection is not None else None,
        candidate_break_point=selection.candidate_break_point if selection is not None else None,
    )


def _parse_report_type(value: str) -> ReportType:
    try:
        return ReportType(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unsupported report type: {value}") from exc


def _report_response(report: ReportModel) -> GeneratedReportResponse:
    return GeneratedReportResponse(
        id=report.id,
        session_id=report.session_id,
        generated_at=report.generated_at,
        report_type=report.report_type,
        content_markdown=report.content_markdown,
        content_json=report.content_json,
        generated_by=report.generated_by,
    )


def _forensic_case_response(forensic_case: ForensicCase) -> ForensicCaseResponse:
    return ForensicCaseResponse(
        id=forensic_case.id,
        session_id=forensic_case.session_id,
        state=forensic_case.state.value,
        report_id=forensic_case.report_id,
        artifact_refs=[ref.to_dict() for ref in forensic_case.artifact_refs],
        review_refs=list(forensic_case.review_refs),
        audit_refs=list(forensic_case.audit_refs),
        created_at=forensic_case.created_at,
        updated_at=forensic_case.updated_at,
    )
