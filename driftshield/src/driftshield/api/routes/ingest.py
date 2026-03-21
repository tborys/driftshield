import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import IngestResponse
from driftshield.cli.parsers import PARSERS
from driftshield.db.ingest_service import TranscriptIngestService
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

    raw_bytes = file.file.read()
    max_request_bytes = int(os.environ.get("MAX_REQUEST_BYTES", str(25 * 1024 * 1024)))
    if len(raw_bytes) > max_request_bytes:
        raise HTTPException(status_code=413, detail=f"Request body exceeds {max_request_bytes} bytes")
    ingest_service = TranscriptIngestService(db)
    try:
        outcome = ingest_service.ingest_bytes(
            raw_bytes=raw_bytes,
            parser_name=normalised,
            source_path=file.filename,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        outcome = PersistenceService(db).get_ingest_outcome(
            IngestProvenance(
                transcript_hash=hashlib.sha256(raw_bytes).hexdigest(),
                source_session_id=None,
                source_path=file.filename,
                parser_version=f"{normalised}@1",
                ingested_at=datetime.now(timezone.utc),
            )
        )
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
