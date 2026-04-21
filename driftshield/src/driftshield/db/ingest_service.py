from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from driftshield.cli.parsers import PARSERS, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import CanonicalEvent, Session as DomainSession, SessionStatus
from driftshield.db.persistence import IngestOutcome, IngestProvenance, PersistenceService


class TranscriptIngestService:
    def __init__(self, db):
        self._db = db

    def ingest_file(
        self,
        *,
        file_path: Path,
        parser_name: str,
        existing_session_id: uuid.UUID | None = None,
    ) -> tuple[IngestOutcome, object]:
        raw_bytes = file_path.read_bytes()
        return self.ingest_bytes(
            raw_bytes=raw_bytes,
            parser_name=parser_name,
            source_path=str(file_path),
            existing_session_id=existing_session_id,
        )

    def ingest_bytes(
        self,
        *,
        raw_bytes: bytes,
        parser_name: str,
        source_path: str | None,
        existing_session_id: uuid.UUID | None = None,
    ) -> tuple[IngestOutcome, object]:
        normalised = parser_name.replace("-", "_")
        if normalised not in PARSERS:
            raise ValueError(f"Unsupported format: {parser_name}")

        parser = get_parser(normalised)
        content = raw_bytes.decode("utf-8")
        events = parser.parse(content)
        if not events:
            raise ValueError("No events parsed from transcript")

        target_session_id = existing_session_id or uuid.uuid4()
        _stabilize_event_ids(events, target_session_id)
        result = analyze_session(events, session_id=str(target_session_id))
        domain_session = DomainSession(
            id=target_session_id,
            agent_id=events[0].agent_id or "unknown",
            started_at=events[0].timestamp,
            external_id=events[0].session_id or None,
            status=SessionStatus.COMPLETED,
        )
        provenance = IngestProvenance(
            transcript_hash=hashlib.sha256(raw_bytes).hexdigest(),
            source_session_id=events[0].session_id or None,
            source_path=source_path,
            parser_version=f"{normalised}@1",
            ingested_at=datetime.now(timezone.utc),
        )
        persistence = PersistenceService(self._db)
        if existing_session_id is None:
            outcome = persistence.ingest(domain_session, result, provenance)
        else:
            outcome = persistence.ingest(
                domain_session,
                result,
                provenance,
                existing_session_id=existing_session_id,
            )
        return outcome, result


def metrics_payload_from_analysis_result(result) -> dict[str, object]:
    risk_summary = result.risk_summary
    matched_families = [family_id for family_id, count in risk_summary.items() if count > 0]
    primary_family_id = None
    if matched_families:
        primary_family_id = max(
            matched_families,
            key=lambda family_id: (risk_summary[family_id], family_id),
        )

    return {
        "outcome_status": "matched" if result.flagged_events > 0 else "unclassified",
        "match_count": result.flagged_events,
        "primary_family_id": primary_family_id,
        "mixed_family": len(matched_families) > 1,
        "not_classifiable_reason": None,
    }


def _stabilize_event_ids(events: list[CanonicalEvent], session_id: uuid.UUID) -> None:
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for index, event in enumerate(events):
        stable_id = uuid.uuid5(
            session_id,
            f"{index}:{event.event_type.value}:{event.action}:{event.agent_id}",
        )
        id_map[event.id] = stable_id

    for event in events:
        original_id = event.id
        event.id = id_map[original_id]
        if event.parent_event_id is not None:
            event.parent_event_id = id_map.get(event.parent_event_id)
