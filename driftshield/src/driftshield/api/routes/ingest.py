import hashlib
import uuid
from datetime import datetime, timezone

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import IngestResponse
from driftshield.cli.parsers import PARSERS, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.db.persistence import IngestProvenance, PersistenceService

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

    normalised = format.replace("-", "_")
    if normalised == "auto":
        normalised = _detect_format(file.filename)
    if normalised not in PARSERS:
        raise HTTPException(status_code=422, detail=f"Unsupported format: {format}")

    parser = get_parser(normalised)
    raw_bytes = file.file.read()
    max_request_bytes = int(os.environ.get("MAX_REQUEST_BYTES", str(25 * 1024 * 1024)))
    if len(raw_bytes) > max_request_bytes:
        raise HTTPException(status_code=413, detail=f"Request body exceeds {max_request_bytes} bytes")

    content = raw_bytes.decode("utf-8")
    events = parser.parse(content)

    if not events:
        raise HTTPException(status_code=422, detail="No events parsed from transcript")

    result = analyze_session(events)
    session_id = uuid.uuid4()
    domain_session = DomainSession(
        id=session_id,
        agent_id=events[0].agent_id or "unknown",
        started_at=events[0].timestamp or datetime.now(timezone.utc),
        external_id=events[0].session_id or None,
        status=SessionStatus.COMPLETED,
    )

    provenance = IngestProvenance(
        transcript_hash=hashlib.sha256(raw_bytes).hexdigest(),
        source_session_id=events[0].session_id or None,
        source_path=file.filename,
        parser_version=f"{normalised}@1",
        ingested_at=datetime.now(timezone.utc),
    )

    service = PersistenceService(db)
    try:
        outcome = service.ingest(domain_session, result, provenance)
        db.commit()
    except IntegrityError:
        db.rollback()
        outcome = service.get_ingest_outcome(provenance)
        if outcome is None:
            raise

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


def _detect_format(filename: str | None) -> str:
    if filename and filename.endswith(".jsonl"):
        return "claude_code"
    return "unknown"
