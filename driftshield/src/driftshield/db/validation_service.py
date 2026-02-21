"""Persistence and export service for analyst validation decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from sqlalchemy.orm import Session as DBSession

from driftshield.db.models import AnalystValidationModel

_ALLOWED_VERDICTS = {"accept", "reject", "needs_review"}


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

        row = AnalystValidationModel(
            session_id=session_id,
            target_type=target_type,
            target_ref=target_ref,
            verdict=verdict,
            confidence=confidence,
            reviewer=reviewer,
            notes=notes,
            metadata_json=metadata_json,
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
            self._db.query(AnalystValidationModel)
            .filter(AnalystValidationModel.shareable.is_(True))
            .order_by(AnalystValidationModel.created_at.asc())
            .all()
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                payload = {
                    "validation_id": str(row.id),
                    "session_id": str(row.session_id),
                    "target_type": row.target_type,
                    "target_ref": row.target_ref,
                    "verdict": row.verdict,
                    "confidence": row.confidence,
                    "reviewer": row.reviewer,
                    "notes": row.notes,
                    "metadata": row.metadata_json,
                    "created_at": row.created_at.isoformat(),
                }
                if row.target_type == "signature" and row.metadata_json:
                    payload["signature_hash"] = row.metadata_json.get("signature_hash")

                f.write(json.dumps(payload, sort_keys=True) + "\n")

        return len(rows)
