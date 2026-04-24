from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.ingest_workflow import ingest_transcript_bytes, read_upload_bytes
from driftshield.api.schemas import IngestResponse

router = APIRouter()


@router.post("/api/ingest", response_model=IngestResponse, status_code=201)
def ingest_transcript(
    response: Response,
    file: UploadFile = File(...),
    format: str = Form(default="auto"),
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    raw_bytes = read_upload_bytes(file)
    outcome, _, _ = ingest_transcript_bytes(
        db,
        raw_bytes=raw_bytes,
        format_name=format,
        filename=file.filename,
    )

    if outcome.deduplicated:
        response.status_code = 200

    return IngestResponse(
        session_id=outcome.session_id,
        total_events=outcome.total_events,
        flagged_events=outcome.flagged_events,
        has_inflection=outcome.has_inflection,
        status=outcome.status,
        deduplicated=outcome.deduplicated,
    )
