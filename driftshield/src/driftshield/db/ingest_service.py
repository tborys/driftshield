from __future__ import annotations

import uuid

from driftshield.core.analysis.session import AnalysisResult
from driftshield.db.persistence import IngestOutcome, PersistenceService
from driftshield.public import AnalysedRun, analyse_run


class TranscriptIngestService:
    """Persist analysed runs. Analysis itself happens behind the public door."""

    def __init__(self, db):
        self._db = db

    def ingest_bytes(
        self,
        *,
        raw_bytes: bytes,
        parser_name: str | None,
        source_path: str | None,
        existing_session_id: uuid.UUID | None = None,
    ) -> tuple[IngestOutcome, AnalysisResult]:
        """Analyse ``raw_bytes`` through the door and persist the run.

        ``parser_name`` forces a format; ``None`` or ``"auto"`` detects it.
        Raises ``ValueError`` (``UnsupportedFormatError`` /
        ``NoParseableEventsError``) when the transcript cannot be analysed.
        """
        run = analyse_run(
            raw_bytes,
            source=source_path,
            format=None if parser_name in (None, "auto") else parser_name,
            run_id=existing_session_id,
        )
        return self.ingest_run(run, existing_session_id=existing_session_id)

    def ingest_run(
        self, run: AnalysedRun, *, existing_session_id: uuid.UUID | None = None
    ) -> tuple[IngestOutcome, AnalysisResult]:
        outcome = PersistenceService(self._db).ingest(
            run.session,
            run.analysis,
            run.provenance,
            existing_session_id=existing_session_id,
        )
        return outcome, run.analysis


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
