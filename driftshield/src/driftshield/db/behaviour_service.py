from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from driftshield.db.models import BehaviourEventModel, BehaviourEventSubjectModel, SessionModel

BehaviourSubjectType = Literal["trusted_pattern", "report", "linked_run_set"]
BehaviourSurface = Literal["api", "ui", "report"]
BehaviourEventType = Literal[
    "pattern_viewed",
    "pattern_expanded",
    "pattern_revisited",
    "pattern_linked_runs_viewed",
    "new_run_after_pattern_view",
]

TRACKABLE_TRUST_BAND = "trusted"
DEFAULT_PATTERN_ACTION_WINDOW_HOURS = 24


@dataclass(frozen=True)
class BehaviourSubjectSnapshot:
    subject: BehaviourEventSubjectModel
    event_counts: dict[str, int]
    tracking_status: str
    follow_up_status: str


class BehaviourEventService:
    def __init__(self, db: DBSession):
        self._db = db

    def create_subject(
        self,
        *,
        subject_type: BehaviourSubjectType,
        pattern_reference: str,
        trust_band: str,
        surface: BehaviourSurface,
        session_id: uuid.UUID | None = None,
        first_exposed_at: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> BehaviourEventSubjectModel:
        first_exposed_at = _ensure_utc(first_exposed_at) or _utc_now()
        subject = BehaviourEventSubjectModel(
            id=uuid.uuid4(),
            session_id=session_id,
            subject_type=subject_type,
            pattern_reference=pattern_reference,
            trust_band=trust_band,
            surface=surface,
            first_exposed_at=first_exposed_at,
            metadata_json=dict(metadata_json or {}),
        )
        self._db.add(subject)
        self._db.flush()
        return subject

    def record_event(
        self,
        *,
        subject_id: uuid.UUID,
        event_type: BehaviourEventType,
        actor_id: str | None = None,
        originating_session_id: str | None = None,
        linked_session_id: uuid.UUID | None = None,
        occurred_at: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> BehaviourEventModel:
        subject = self._db.get(BehaviourEventSubjectModel, subject_id)
        if subject is None:
            raise LookupError("Behaviour subject not found")

        event = BehaviourEventModel(
            id=uuid.uuid4(),
            subject_id=subject_id,
            occurred_at=_ensure_utc(occurred_at) or _utc_now(),
            event_type=event_type,
            actor_id=actor_id,
            originating_session_id=originating_session_id,
            linked_session_id=linked_session_id,
            metadata_json=dict(metadata_json or {}),
        )
        self._db.add(event)
        self._db.flush()
        return event

    def get_subject_snapshot(self, subject_id: uuid.UUID) -> BehaviourSubjectSnapshot | None:
        subject = self._db.get(BehaviourEventSubjectModel, subject_id)
        if subject is None:
            return None

        counts = self._event_counts(subject_id)
        tracking_status = "live" if subject.trust_band == TRACKABLE_TRUST_BAND else "unavailable"
        if tracking_status != "live" or counts.get("pattern_viewed", 0) == 0:
            follow_up_status = "unavailable"
        elif counts.get("new_run_after_pattern_view", 0) > 0:
            follow_up_status = "linked"
        else:
            follow_up_status = "no_follow_up_observed"

        return BehaviourSubjectSnapshot(
            subject=subject,
            event_counts=counts,
            tracking_status=tracking_status,
            follow_up_status=follow_up_status,
        )

    def link_new_run_after_pattern_view(
        self,
        *,
        session_id: uuid.UUID,
        window_hours: int = DEFAULT_PATTERN_ACTION_WINDOW_HOURS,
    ) -> int:
        session = self._db.get(SessionModel, session_id)
        if session is None or not session.agent_id:
            return 0

        if session.started_at.tzinfo is None:
            session_started_at = session.started_at.replace(tzinfo=UTC)
        else:
            session_started_at = session.started_at.astimezone(UTC)

        window_start = session_started_at - timedelta(hours=window_hours)

        subject_rows = self._db.execute(
            select(BehaviourEventSubjectModel)
            .join(
                BehaviourEventModel,
                BehaviourEventModel.subject_id == BehaviourEventSubjectModel.id,
            )
            .where(BehaviourEventSubjectModel.trust_band == TRACKABLE_TRUST_BAND)
            .where(BehaviourEventModel.event_type == "pattern_viewed")
            .where(BehaviourEventModel.actor_id == session.agent_id)
            .where(BehaviourEventModel.occurred_at >= window_start)
            .where(BehaviourEventModel.occurred_at <= session_started_at)
            .distinct()
        ).scalars()

        linked_count = 0
        for subject in subject_rows:
            existing = self._db.execute(
                select(BehaviourEventModel.id)
                .where(BehaviourEventModel.subject_id == subject.id)
                .where(BehaviourEventModel.event_type == "new_run_after_pattern_view")
                .where(BehaviourEventModel.linked_session_id == session.id)
            ).scalar_one_or_none()
            if existing is not None:
                continue

            self.record_event(
                subject_id=subject.id,
                event_type="new_run_after_pattern_view",
                actor_id=session.agent_id,
                originating_session_id=session.source_session_id,
                linked_session_id=session.id,
                occurred_at=session_started_at,
                metadata_json={
                    "window_hours": window_hours,
                    "linked_via": "agent_id",
                    "tracking_boundary": "behaviour_events_v1",
                },
            )
            linked_count += 1

        return linked_count

    def _event_counts(self, subject_id: uuid.UUID) -> dict[str, int]:
        rows = self._db.execute(
            select(BehaviourEventModel.event_type, func.count(BehaviourEventModel.id))
            .where(BehaviourEventModel.subject_id == subject_id)
            .group_by(BehaviourEventModel.event_type)
        ).all()
        return {event_type: count for event_type, count in rows}


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
