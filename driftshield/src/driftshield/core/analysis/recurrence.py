"""Recurrence detection primitives for cross-session failure pattern matching."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from driftshield.core.models import CanonicalEvent


class RecurrenceLevel(StrEnum):
    NEW = "new"
    RECURRING = "recurring"
    SYSTEMIC = "systemic"


@dataclass(slots=True)
class RecurrenceAssessment:
    signature_hash: str
    occurrence_count: int
    level: RecurrenceLevel
    probability: str


class RecurrenceEngine:
    """Generate signature hashes and classify recurrence severity."""

    def signature_hash(self, events: list[CanonicalEvent]) -> str:
        risk_counts: dict[str, int] = {
            "assumption_mutation": 0,
            "policy_divergence": 0,
            "constraint_violation": 0,
            "context_contamination": 0,
            "coverage_gap": 0,
        }
        flagged_sequence: list[dict[str, object]] = []

        for idx, event in enumerate(events):
            active_flags: list[str] = []
            rc = event.risk_classification
            if rc is not None and rc.has_any_flag():
                active_flags = sorted(rc.active_flags())
                for flag in active_flags:
                    risk_counts[flag] = risk_counts.get(flag, 0) + 1

            if active_flags:
                flagged_sequence.append(
                    {
                        "index": idx,
                        "event_type": event.event_type.value,
                        "action": event.action,
                        "flags": active_flags,
                    }
                )

        payload = {
            "risk_counts": risk_counts,
            "flagged_sequence": flagged_sequence,
            "total_events": len(events),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def evaluate(
        self,
        events: list[CanonicalEvent],
        historical_counts: dict[str, int] | None = None,
    ) -> RecurrenceAssessment:
        history = historical_counts or {}
        sig_hash = self.signature_hash(events)
        previous = history.get(sig_hash, 0)
        occurrence_count = previous + 1

        if occurrence_count >= 6:
            level = RecurrenceLevel.SYSTEMIC
            probability = "high"
        elif occurrence_count >= 3:
            level = RecurrenceLevel.RECURRING
            probability = "medium"
        else:
            level = RecurrenceLevel.NEW
            probability = "low"

        return RecurrenceAssessment(
            signature_hash=sig_hash,
            occurrence_count=occurrence_count,
            level=level,
            probability=probability,
        )
