import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.db.models import SessionModel, ReportModel

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
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        report_type=request.report_type,
        content_markdown=f"# Forensic Analysis Report\n\nSession: {session_id}\n",
        content_json={"session_id": str(session_id), "sections": []},
        generated_by="system",
    )
    db.add(report)
    db.flush()

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
