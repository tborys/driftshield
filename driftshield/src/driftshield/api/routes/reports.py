import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.core.analysis.inflection import select_inflection_node
from driftshield.core.analysis.session import AnalysisResult
from driftshield.db.models import SessionModel, ReportModel
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
):
    session_model = db.get(SessionModel, session_id)
    if session_model is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = PersistenceService(db)
    domain_session = service.load_session(session_id)
    graph = service.load_graph(session_id)

    if graph is None:
        raise HTTPException(status_code=404, detail="No graph data for session")

    # Reconstruct AnalysisResult from stored data
    selection = select_inflection_node(graph, graph.nodes[-1].id) if graph.nodes else None
    events = [node.event for node in graph.nodes]
    flagged = sum(
        1 for e in events if e.risk_classification and e.risk_classification.has_any_flag()
    )

    result = AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=selection.node if selection is not None else None,
        total_events=len(events),
        flagged_events=flagged,
        inflection_explanation=selection.explanation if selection is not None else None,
        candidate_break_point=selection.candidate_break_point if selection is not None else None,
    )

    report_type = ReportType(request.report_type)
    builder = ReportBuilder()
    report_data = builder.build(domain_session, result, report_type=report_type)

    md = render_markdown(report_data)
    json_content = export_json(report_data)

    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=report_data.generated_at,
        report_type=report_type.value,
        content_markdown=md,
        content_json=json_content,
        generated_by="system",
    )
    db.add(report)
    db.flush()
    service.upsert_forensic_case(domain_session, result, report=report)

    return {"id": report.id, "report_type": report.report_type}


@router.get("/api/sessions/{session_id}/reports")
def list_session_reports(
    session_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
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
):
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
