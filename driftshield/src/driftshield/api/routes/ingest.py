import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import IngestResponse
from driftshield.cli.parsers import get_parser, PARSERS
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.db.persistence import PersistenceService

router = APIRouter()


@router.post("/api/ingest", response_model=IngestResponse, status_code=201)
def ingest_transcript(
    file: UploadFile = File(...),
    format: str = Form(default="auto"),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    # Normalise format name (allow hyphens or underscores)
    normalised = format.replace("-", "_")

    if normalised == "auto":
        normalised = _detect_format(file.filename)
    if normalised not in PARSERS:
        raise HTTPException(status_code=422, detail=f"Unsupported format: {format}")

    parser = get_parser(normalised)
    content = file.file.read().decode("utf-8")
    events = parser.parse(content)

    if not events:
        raise HTTPException(status_code=422, detail="No events parsed from transcript")

    result = analyze_session(events)

    session_id = uuid.uuid4()
    domain_session = DomainSession(
        id=session_id,
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp or datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )

    service = PersistenceService(db)
    service.save(domain_session, result)

    return IngestResponse(
        session_id=session_id,
        total_events=result.total_events,
        flagged_events=result.flagged_events,
        has_inflection=result.inflection_node is not None,
    )


def _detect_format(filename: str | None) -> str:
    if filename and filename.endswith(".jsonl"):
        return "claude_code"
    return "unknown"
