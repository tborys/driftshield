import uuid
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.api.schemas import (
    BehaviourEventCreateRequest,
    BehaviourEventResponse,
    BehaviourSubjectCreateRequest,
    BehaviourSubjectResponse,
)
from driftshield.db.behaviour_service import BehaviourEventService
from driftshield.db.models import SessionModel

router = APIRouter()

SubjectType = Literal["trusted_pattern", "report", "linked_run_set"]
SurfaceType = Literal["api", "ui", "report"]
EventType = Literal[
    "pattern_viewed",
    "pattern_expanded",
    "pattern_revisited",
    "pattern_linked_runs_viewed",
    "new_run_after_pattern_view",
]

_ALLOWED_SUBJECT_TYPES = {"trusted_pattern", "report", "linked_run_set"}
_ALLOWED_SURFACES = {"api", "ui", "report"}
_ALLOWED_EVENT_TYPES = {
    "pattern_viewed",
    "pattern_expanded",
    "pattern_revisited",
    "pattern_linked_runs_viewed",
    "new_run_after_pattern_view",
}


@router.post("/api/behaviour/subjects", response_model=BehaviourSubjectResponse, status_code=201)
def create_behaviour_subject(
    payload: BehaviourSubjectCreateRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    _validate_subject_payload(payload)
    _require_session_exists(db, payload.session_id, detail="Behaviour subject session not found")

    service = BehaviourEventService(db)
    subject = service.create_subject(
        subject_type=cast(SubjectType, payload.subject_type),
        pattern_reference=payload.pattern_reference,
        trust_band=payload.trust_band,
        surface=cast(SurfaceType, payload.surface),
        session_id=payload.session_id,
        first_exposed_at=payload.first_exposed_at,
        metadata_json=payload.metadata_json,
    )
    snapshot = service.get_subject_snapshot(subject.id)
    assert snapshot is not None
    db.commit()
    return _subject_response(snapshot)


@router.get("/api/behaviour/subjects/{subject_id}", response_model=BehaviourSubjectResponse)
def get_behaviour_subject(
    subject_id: uuid.UUID,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    snapshot = BehaviourEventService(db).get_subject_snapshot(subject_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Behaviour subject not found")
    return _subject_response(snapshot)


@router.post("/api/behaviour/events", response_model=BehaviourEventResponse, status_code=201)
def create_behaviour_event(
    payload: BehaviourEventCreateRequest,
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
):
    del api_key
    if payload.event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported behaviour event type")
    _require_session_exists(
        db,
        payload.linked_session_id,
        detail="Linked behaviour event session not found",
    )

    service = BehaviourEventService(db)
    try:
        event = service.record_event(
            subject_id=payload.subject_id,
            event_type=cast(EventType, payload.event_type),
            actor_id=payload.actor_id,
            originating_session_id=payload.originating_session_id,
            linked_session_id=payload.linked_session_id,
            occurred_at=payload.occurred_at,
            metadata_json=payload.metadata_json,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    db.commit()
    return BehaviourEventResponse(
        id=event.id,
        subject_id=event.subject_id,
        occurred_at=event.occurred_at,
        event_type=event.event_type,
        actor_id=event.actor_id,
        originating_session_id=event.originating_session_id,
        linked_session_id=event.linked_session_id,
        metadata_json=event.metadata_json or {},
    )


def _validate_subject_payload(payload: BehaviourSubjectCreateRequest) -> None:
    if payload.subject_type not in _ALLOWED_SUBJECT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported behaviour subject type")
    if payload.surface not in _ALLOWED_SURFACES:
        raise HTTPException(status_code=422, detail="Unsupported behaviour surface")
    if payload.subject_type != "trusted_pattern" and payload.trust_band == "trusted":
        raise HTTPException(
            status_code=422,
            detail="Only trusted_pattern subjects can be marked trusted in OSS v1",
        )


def _require_session_exists(
    db: DBSession,
    session_id: uuid.UUID | None,
    *,
    detail: str,
) -> None:
    if session_id is None:
        return
    if db.get(SessionModel, session_id) is None:
        raise HTTPException(status_code=404, detail=detail)


def _subject_response(snapshot) -> BehaviourSubjectResponse:
    subject = snapshot.subject
    return BehaviourSubjectResponse(
        id=subject.id,
        session_id=subject.session_id,
        subject_type=subject.subject_type,
        pattern_reference=subject.pattern_reference,
        trust_band=subject.trust_band,
        surface=subject.surface,
        first_exposed_at=subject.first_exposed_at,
        metadata_json=subject.metadata_json or {},
        tracking_status=snapshot.tracking_status,
        follow_up_status=snapshot.follow_up_status,
        event_counts=snapshot.event_counts,
    )
