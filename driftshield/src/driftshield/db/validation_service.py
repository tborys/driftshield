"""Persistence and export service for analyst validation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from sqlalchemy.orm import Session as DBSession

from driftshield.db.models import AnalystValidationModel, SessionModel

_ALLOWED_VERDICTS = {"accept", "reject", "needs_review"}
_ALLOWED_REVIEW_OUTCOMES = {
    "useful_failure",
    "noise",
    "true_inflection",
    "wrong_inflection",
    "needs_follow_up",
}
_REVIEW_OUTCOME_VERDICTS = {
    "useful_failure": "accept",
    "true_inflection": "accept",
    "noise": "reject",
    "wrong_inflection": "reject",
    "needs_follow_up": "needs_review",
}


@dataclass(slots=True)
class ValidationRecord:
    id: uuid.UUID
    session_id: uuid.UUID
    target_type: str
    target_ref: str
    verdict: str
    confidence: float | None
    reviewer: str
    notes: str | None
    metadata_json: dict | None
    shareable: bool
    created_at: datetime


class ValidationService:
    def __init__(self, db: DBSession):
        self._db = db

    def _normalise_metadata(self, metadata_json: dict | None) -> dict | None:
        if metadata_json is None:
            return None

        metadata = dict(metadata_json)
        review_outcome = metadata.get("review_outcome")
        if review_outcome is not None:
            if not isinstance(review_outcome, dict):
                raise ValueError("review_outcome metadata must be an object")

            label = review_outcome.get("label")
            if label not in _ALLOWED_REVIEW_OUTCOMES:
                allowed = ", ".join(sorted(_ALLOWED_REVIEW_OUTCOMES))
                raise ValueError(f"review_outcome.label must be one of: {allowed}")

            target_type = review_outcome.get("target_type")
            if target_type is not None and not isinstance(target_type, str):
                raise ValueError("review_outcome.target_type must be a string")

            expected_verdict = _REVIEW_OUTCOME_VERDICTS[label]
            if metadata.get("verdict") not in (None, expected_verdict):
                raise ValueError(
                    f"review_outcome.label {label!r} requires verdict {expected_verdict!r}"
                )

        return metadata

    def _record(
        self,
        *,
        session_id: uuid.UUID,
        target_type: str,
        target_ref: str,
        verdict: str,
        reviewer: str,
        confidence: float | None,
        notes: str | None,
        metadata_json: dict | None,
        shareable: bool,
    ) -> AnalystValidationModel:
        if verdict not in _ALLOWED_VERDICTS:
            raise ValueError("verdict must be accept/reject/needs_review")

        normalised_metadata = self._normalise_metadata(
            None if metadata_json is None else {**metadata_json, "verdict": verdict}
        )
        if normalised_metadata is not None:
            normalised_metadata.pop("verdict", None)

        row = AnalystValidationModel(
            session_id=session_id,
            target_type=target_type,
            target_ref=target_ref,
            verdict=verdict,
            confidence=confidence,
            reviewer=reviewer,
            notes=notes,
            metadata_json=normalised_metadata,
            shareable=shareable,
            created_at=datetime.now(timezone.utc),
        )
        self._db.add(row)
        self._db.flush()
        return row

    def record_inflection_validation(
        self,
        *,
        session_id: uuid.UUID,
        node_id: uuid.UUID,
        verdict: str,
        reviewer: str,
        confidence: float | None = None,
        notes: str | None = None,
        shareable: bool = False,
    ) -> AnalystValidationModel:
        return self._record(
            session_id=session_id,
            target_type="inflection",
            target_ref=str(node_id),
            verdict=verdict,
            reviewer=reviewer,
            confidence=confidence,
            notes=notes,
            metadata_json=None,
            shareable=shareable,
        )

    def record_risk_flag_validation(
        self,
        *,
        session_id: uuid.UUID,
        node_id: uuid.UUID,
        flag_name: str,
        verdict: str,
        reviewer: str,
        confidence: float | None = None,
        notes: str | None = None,
        shareable: bool = False,
    ) -> AnalystValidationModel:
        return self._record(
            session_id=session_id,
            target_type="risk_flag",
            target_ref=f"{node_id}:{flag_name}",
            verdict=verdict,
            reviewer=reviewer,
            confidence=confidence,
            notes=notes,
            metadata_json={"flag_name": flag_name, "node_id": str(node_id)},
            shareable=shareable,
        )

    def record_signature_validation(
        self,
        *,
        session_id: uuid.UUID,
        signature_hash: str,
        verdict: str,
        reviewer: str,
        confidence: float | None = None,
        notes: str | None = None,
        shareable: bool = False,
    ) -> AnalystValidationModel:
        return self._record(
            session_id=session_id,
            target_type="signature",
            target_ref=signature_hash,
            verdict=verdict,
            reviewer=reviewer,
            confidence=confidence,
            notes=notes,
            metadata_json={"signature_hash": signature_hash},
            shareable=shareable,
        )

    def list_validations(
        self,
        *,
        session_id: uuid.UUID | None = None,
    ) -> list[ValidationRecord]:
        query = self._db.query(AnalystValidationModel).order_by(
            AnalystValidationModel.created_at.asc()
        )
        if session_id is not None:
            query = query.filter(AnalystValidationModel.session_id == session_id)

        return [
            ValidationRecord(
                id=row.id,
                session_id=row.session_id,
                target_type=row.target_type,
                target_ref=row.target_ref,
                verdict=row.verdict,
                confidence=row.confidence,
                reviewer=row.reviewer,
                notes=row.notes,
                metadata_json=row.metadata_json,
                shareable=row.shareable,
                created_at=row.created_at,
            )
            for row in query.all()
        ]

    def export_training_dataset_jsonl(self, path: Path) -> int:
        rows = (
            self._db.query(AnalystValidationModel, SessionModel)
            .join(SessionModel, SessionModel.id == AnalystValidationModel.session_id)
            .filter(AnalystValidationModel.shareable.is_(True))
            .order_by(AnalystValidationModel.created_at.asc())
            .all()
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for validation, session in rows:
                review_outcome = None
                if validation.metadata_json:
                    outcome = validation.metadata_json.get("review_outcome")
                    if isinstance(outcome, dict):
                        review_outcome = outcome

                payload = {
                    "validation_id": str(validation.id),
                    "session_id": str(validation.session_id),
                    "target_type": validation.target_type,
                    "target_ref": validation.target_ref,
                    "verdict": validation.verdict,
                    "confidence": validation.confidence,
                    "reviewer": validation.reviewer,
                    "notes": validation.notes,
                    "metadata": validation.metadata_json,
                    "review_outcome": review_outcome,
                    "created_at": validation.created_at.isoformat(),
                    "session_provenance": {
                        "source_session_id": session.source_session_id,
                        "source_path": session.source_path,
                        "parser_version": session.parser_version,
                        "transcript_hash": session.transcript_hash,
                        "ingested_at": session.ingested_at.isoformat() if session.ingested_at else None,
                    },
                }
                if validation.target_type == "signature" and validation.metadata_json:
                    payload["signature_hash"] = validation.metadata_json.get("signature_hash")

                f.write(json.dumps(payload, sort_keys=True) + "\n")

        return len(rows)
