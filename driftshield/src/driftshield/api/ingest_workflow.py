from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from driftshield.api.security import get_max_request_bytes
from driftshield.core.analysis.session import AnalysisResult
from driftshield.db.behaviour_service import BehaviourEventService
from driftshield.db.ingest_service import TranscriptIngestService, metrics_payload_from_analysis_result
from driftshield.db.persistence import IngestOutcome, PersistenceService
from driftshield.public import analyse_run
from driftshield.telemetry import TelemetryService


def ingest_transcript_bytes(
    db: DBSession,
    *,
    raw_bytes: bytes,
    format_name: str,
    filename: str | None,
    commit: bool = True,
) -> tuple[IngestOutcome, AnalysisResult | None, str]:
    _validate_request_size(raw_bytes)
    try:
        run = analyse_run(
            raw_bytes,
            source=filename,
            format=None if format_name == "auto" else format_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalised = run.detected_format

    ingest_service = TranscriptIngestService(db)
    try:
        outcome, analysis_result = ingest_service.ingest_run(run)
        if not outcome.deduplicated and analysis_result is not None and analysis_result.events:
            BehaviourEventService(db).link_new_run_after_pattern_view(session_id=outcome.session_id)
        if commit:
            db.commit()
            if not outcome.deduplicated and analysis_result is not None:
                record_analysis_telemetry(analysis_result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        outcome = PersistenceService(db).get_ingest_outcome(run.provenance)
        if outcome is None:
            raise
        analysis_result = None
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Failed to process transcript: {exc}",
        ) from exc

    return outcome, analysis_result, normalised


def read_upload_bytes(
    file: UploadFile,
    *,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    max_request_bytes = get_max_request_bytes()
    total_bytes = 0
    chunks: list[bytes] = []

    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break

        total_bytes += len(chunk)
        if total_bytes > max_request_bytes:
            raise HTTPException(status_code=413, detail=f"Request body exceeds {max_request_bytes} bytes")
        chunks.append(chunk)

    return b"".join(chunks)


def record_analysis_telemetry(result: AnalysisResult) -> None:
    metrics = metrics_payload_from_analysis_result(result)
    try:
        TelemetryService().record_analysis_event(
            outcome_status=metrics["outcome_status"],
            match_count=metrics["match_count"],
            primary_mechanism_id=metrics["primary_family_id"],
            mixed_mechanism=metrics["mixed_family"],
            not_classifiable_reason=metrics["not_classifiable_reason"],
        )
    except Exception:
        pass


def _validate_request_size(raw_bytes: bytes) -> None:
    max_request_bytes = get_max_request_bytes()
    if len(raw_bytes) > max_request_bytes:
        raise HTTPException(status_code=413, detail=f"Request body exceeds {max_request_bytes} bytes")
