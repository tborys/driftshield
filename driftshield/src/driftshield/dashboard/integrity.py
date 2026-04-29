from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy.orm import Session as DBSession

from driftshield.db.models import AnalystValidationModel, SessionModel

STALE_THRESHOLD_HOURS = 24


@dataclass(slots=True)
class IntegrityRecord:
    trust_band: str
    structural_score: float
    semantic_score: float
    source_factor: float
    pattern_integrity_score: float
    final_learning_weight: float
    integrity_reasons: list[str]
    requires_review: bool
    integrity_evaluated_at: datetime | None
    ingested_at: datetime | None
    source_session_id: str | None
    source_path: str | None


class IntegrityDashboardService:
    def __init__(self, db: DBSession):
        self._db = db

    def build_dashboard_payload(self) -> dict[str, dict[str, Any]]:
        computed_at = datetime.now(timezone.utc)
        records = self._load_records()

        return {
            "integrity_intake_summary": self._integrity_intake_summary(records, computed_at),
            "learning_weight_breakdown": self._learning_weight_breakdown(records, computed_at),
            "quarantine_review_summary": self._quarantine_review_summary(records, computed_at),
            "integrity_freshness_summary": self._integrity_freshness_summary(records, computed_at),
            "source_integrity_summary": self._source_integrity_summary(records, computed_at),
            "recurrence_quality_summary": self._gated_summary(
                computed_at,
                blocked_by=["private_recurrence_engine", "cross_run_learning_store"],
                caveats=[
                    "Recurrence quality is gated in OSS v1 because recurrence engines and cross-run learning remain out of scope."
                ],
            ),
            "pattern_promotion_summary": self._gated_summary(
                computed_at,
                blocked_by=["private_pattern_promotion", "private_pattern_suppression"],
                caveats=[
                    "Pattern promotion and suppression remain private-layer concerns and are not live OSS metrics."
                ],
            ),
            "threshold_calibration_summary": self._threshold_calibration_summary(records, computed_at),
        }

    def _load_records(self) -> list[IntegrityRecord]:
        rows = self._db.query(SessionModel).all()
        records: list[IntegrityRecord] = []
        for row in rows:
            metadata = row.metadata_json or {}
            payload = metadata.get("integrity_summary")
            if not isinstance(payload, dict):
                continue
            evaluated_at = _parse_datetime(payload.get("integrity_evaluated_at"))
            records.append(
                IntegrityRecord(
                    trust_band=str(payload.get("trust_band") or "unknown"),
                    structural_score=_float_value(payload.get("structural_score")),
                    semantic_score=_float_value(payload.get("semantic_score")),
                    source_factor=_float_value(payload.get("source_factor")),
                    pattern_integrity_score=_float_value(payload.get("pattern_integrity_score")),
                    final_learning_weight=_float_value(payload.get("final_learning_weight")),
                    integrity_reasons=_string_list(payload.get("integrity_reasons")),
                    requires_review=bool(payload.get("requires_review")),
                    integrity_evaluated_at=_normalize_datetime(evaluated_at),
                    ingested_at=_normalize_datetime(row.ingested_at),
                    source_session_id=row.source_session_id,
                    source_path=row.source_path,
                )
            )
        return records

    def _integrity_intake_summary(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        weights = sorted(record.final_learning_weight for record in records)
        trust_counts = Counter(record.trust_band for record in records)
        latest_freshness = max(
            (record.integrity_evaluated_at for record in records if record.integrity_evaluated_at),
            default=None,
        )
        return _artifact(
            status="live",
            computed_at=computed_at,
            metrics={
                "total_runs_ingested": len(records),
                "trusted_count": trust_counts.get("trusted", 0),
                "provisional_count": trust_counts.get("provisional", 0),
                "quarantined_count": trust_counts.get("quarantined", 0),
                "average_structural_score": _average(record.structural_score for record in records),
                "average_semantic_score": _average(record.semantic_score for record in records),
                "final_learning_weight_percentiles": {
                    "p10": _percentile(weights, 10),
                    "p50": _percentile(weights, 50),
                    "p90": _percentile(weights, 90),
                },
                "latest_freshness_timestamp": _isoformat(latest_freshness),
            },
        )

    def _learning_weight_breakdown(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        reason_counts = Counter(
            reason
            for record in records
            for reason in record.integrity_reasons
        )
        return _artifact(
            status="live",
            computed_at=computed_at,
            metrics={
                "average_structural_score": _average(record.structural_score for record in records),
                "average_semantic_score": _average(record.semantic_score for record in records),
                "average_source_factor": _average(record.source_factor for record in records),
                "average_pattern_integrity_score": _average(
                    record.pattern_integrity_score for record in records
                ),
                "final_learning_weight_buckets": _weight_buckets(records),
                "top_downgrade_reasons": [
                    {"reason": reason, "count": count}
                    for reason, count in reason_counts.most_common(5)
                ],
            },
        )

    def _quarantine_review_summary(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        quarantined_records = [record for record in records if record.trust_band == "quarantined"]
        reviewed_ids = {
            row.session_id
            for row in self._db.query(AnalystValidationModel).filter(
                AnalystValidationModel.target_type == "forensic_feedback"
            )
        }
        session_rows = self._db.query(SessionModel.id, SessionModel.metadata_json).all()
        quarantined_ids = {
            row_id
            for row_id, metadata in session_rows
            if isinstance(metadata, dict)
            and isinstance(metadata.get("integrity_summary"), dict)
            and metadata["integrity_summary"].get("trust_band") == "quarantined"
        }
        reviewed_count = len(quarantined_ids & reviewed_ids)
        return _artifact(
            status="live",
            computed_at=computed_at,
            metrics={
                "quarantined_count": len(quarantined_records),
                "quarantine_reason_counts": [
                    {"reason": reason, "count": count}
                    for reason, count in Counter(
                        reason
                        for record in quarantined_records
                        for reason in record.integrity_reasons
                    ).most_common()
                ],
                "requires_review_count": sum(1 for record in records if record.requires_review),
                "reviewed_count": reviewed_count,
                "unreviewed_count": max(len(quarantined_ids) - reviewed_count, 0),
                "freshness_timestamp": _isoformat(
                    max(
                        (record.integrity_evaluated_at for record in quarantined_records if record.integrity_evaluated_at),
                        default=None,
                    )
                ),
            },
        )

    def _integrity_freshness_summary(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        latest_freshness = max(
            (record.integrity_evaluated_at for record in records if record.integrity_evaluated_at),
            default=None,
        )
        average_latency = _average(
            (
                (record.integrity_evaluated_at - record.ingested_at).total_seconds()
                for record in records
                if record.integrity_evaluated_at and record.ingested_at
            )
        )
        stale = True
        if latest_freshness is not None:
            stale = (computed_at - latest_freshness) > _stale_delta()
        return _artifact(
            status="live",
            computed_at=computed_at,
            metrics={
                "last_successful_dashboard_update_time": computed_at.isoformat(),
                "latest_freshness_timestamp": _isoformat(latest_freshness),
                "average_ingestion_to_integrity_latency_seconds": average_latency,
                "stale_data": stale,
                "stale_threshold_hours": STALE_THRESHOLD_HOURS,
            },
        )

    def _source_integrity_summary(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        locator_count = sum(
            1 for record in records if record.source_session_id is not None or record.source_path is not None
        )
        if records and locator_count != len(records):
            return _artifact(
                status="gated",
                computed_at=computed_at,
                metrics={"runs_with_source_locator": locator_count, "total_runs": len(records)},
                blocked_by=["source_session_id", "source_path"],
                caveats=[
                    "Source integrity summary is gated until source identifier granularity is present in an OSS-safe way for all runs in scope."
                ],
            )
        return _artifact(
            status="live",
            computed_at=computed_at,
            metrics={
                "runs_with_source_locator": locator_count,
                "total_runs": len(records),
                "source_coverage_ratio": round(locator_count / len(records), 4) if records else 0.0,
            },
        )

    def _threshold_calibration_summary(
        self, records: list[IntegrityRecord], computed_at: datetime
    ) -> dict[str, Any]:
        if not records:
            status = "gated"
            caveats = ["No integrity history is available yet."]
            blocked_by = ["integrity_history"]
        else:
            status = "directional"
            caveats = [
                "Threshold calibration remains directional until reviewed outcomes accumulate across enough live integrity history."
            ]
            blocked_by = ["reviewed_outcomes_volume"]
        return _artifact(
            status=status,
            computed_at=computed_at,
            metrics={
                "observed_run_count": len(records),
                "current_thresholds": {
                    "trusted": 0.70,
                    "provisional": 0.40,
                    "quarantined_below": 0.40,
                },
                "median_final_learning_weight": median(
                    [record.final_learning_weight for record in records]
                )
                if records
                else None,
            },
            blocked_by=blocked_by,
            caveats=caveats,
        )

    def _gated_summary(
        self,
        computed_at: datetime,
        *,
        blocked_by: list[str],
        caveats: list[str],
    ) -> dict[str, Any]:
        return _artifact(
            status="gated",
            computed_at=computed_at,
            metrics={},
            blocked_by=blocked_by,
            caveats=caveats,
        )


def _artifact(
    *,
    status: str,
    computed_at: datetime,
    metrics: dict[str, Any],
    blocked_by: list[str] | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "computed_at": computed_at.isoformat(),
        "time_window": "all_time",
        "metrics": metrics,
        "blocked_by": blocked_by or [],
        "caveats": caveats or [],
    }


def _float_value(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if isinstance(value, str):
        try:
            return _normalize_datetime(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _average(values: Any) -> float | None:
    collected = [float(value) for value in values]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 4)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    if percentile <= 0:
        return values[0]
    if percentile >= 100:
        return values[-1]
    index = round((len(values) - 1) * (percentile / 100))
    return values[index]


def _weight_buckets(records: list[IntegrityRecord]) -> list[dict[str, Any]]:
    bounds = [
        ("0.00-0.24", 0.0, 0.25),
        ("0.25-0.39", 0.25, 0.40),
        ("0.40-0.69", 0.40, 0.70),
        ("0.70-1.00", 0.70, 1.01),
    ]
    result = []
    for label, lower, upper in bounds:
        result.append(
            {
                "bucket": label,
                "count": sum(
                    1
                    for record in records
                    if lower <= record.final_learning_weight < upper
                ),
            }
        )
    return result


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _stale_delta() -> timedelta:
    return timedelta(hours=STALE_THRESHOLD_HOURS)
