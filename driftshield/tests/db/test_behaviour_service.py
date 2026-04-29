import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.behaviour_service import BehaviourEventService
from driftshield.db.models import Base, BehaviourEventModel, BehaviourEventSubjectModel, SessionModel


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_behaviour_subject_creation_and_persistence():
    with _db_session() as db:
        service = BehaviourEventService(db)
        session_id = uuid.uuid4()
        db.add(SessionModel(id=session_id, started_at=datetime.now(UTC), status="completed"))
        db.flush()

        subject = service.create_subject(
            subject_type="trusted_pattern",
            pattern_reference="pattern:coverage-gap",
            trust_band="trusted",
            surface="api",
            session_id=session_id,
        )
        db.commit()

        loaded = db.get(BehaviourEventSubjectModel, subject.id)
        assert loaded is not None
        assert loaded.subject_type == "trusted_pattern"
        assert loaded.pattern_reference == "pattern:coverage-gap"
        assert loaded.trust_band == "trusted"
        assert loaded.surface == "api"
        assert loaded.session_id == session_id


def test_behaviour_event_persists_all_v1_event_types():
    with _db_session() as db:
        service = BehaviourEventService(db)
        subject = service.create_subject(
            subject_type="trusted_pattern",
            pattern_reference="pattern:coverage-gap",
            trust_band="trusted",
            surface="ui",
        )

        event_types = [
            "pattern_viewed",
            "pattern_expanded",
            "pattern_revisited",
            "pattern_linked_runs_viewed",
            "new_run_after_pattern_view",
        ]
        for event_type in event_types:
            service.record_event(subject_id=subject.id, event_type=event_type, actor_id="acct-1")
        db.commit()

        rows = db.query(BehaviourEventModel).filter(BehaviourEventModel.subject_id == subject.id).all()
        assert {row.event_type for row in rows} == set(event_types)


def test_trusted_pattern_view_links_to_new_run_after_follow_up_ingest():
    with _db_session() as db:
        service = BehaviourEventService(db)
        viewed_at = datetime.now(UTC) - timedelta(hours=2)
        subject = service.create_subject(
            subject_type="trusted_pattern",
            pattern_reference="pattern:verification-failure",
            trust_band="trusted",
            surface="report",
            first_exposed_at=viewed_at,
        )
        service.record_event(
            subject_id=subject.id,
            event_type="pattern_viewed",
            actor_id="claude-code",
            occurred_at=viewed_at,
        )

        new_session_id = uuid.uuid4()
        db.add(
            SessionModel(
                id=new_session_id,
                agent_id="claude-code",
                started_at=datetime.now(UTC),
                status="completed",
                source_session_id="follow-up-run-1",
            )
        )
        db.flush()

        linked_count = service.link_new_run_after_pattern_view(session_id=new_session_id)
        db.commit()

        assert linked_count == 1
        linked = (
            db.query(BehaviourEventModel)
            .filter(BehaviourEventModel.subject_id == subject.id)
            .filter(BehaviourEventModel.event_type == "new_run_after_pattern_view")
            .one()
        )
        assert linked.actor_id == "claude-code"
        assert linked.originating_session_id == "follow-up-run-1"
        assert linked.linked_session_id == new_session_id


def test_behaviour_events_do_not_depend_on_generic_telemetry_state():
    with _db_session() as db:
        service = BehaviourEventService(db)
        subject = service.create_subject(
            subject_type="trusted_pattern",
            pattern_reference="pattern:coverage-gap",
            trust_band="trusted",
            surface="api",
            metadata_json={"distinction": "not telemetry"},
        )
        event = service.record_event(
            subject_id=subject.id,
            event_type="pattern_viewed",
            actor_id="acct-2",
            metadata_json={"source": "behaviour_events_v1"},
        )
        db.commit()

        assert event.metadata_json == {"source": "behaviour_events_v1"}
        snapshot = service.get_subject_snapshot(subject.id)
        assert snapshot is not None
        assert snapshot.tracking_status == "live"
        assert snapshot.follow_up_status == "no_follow_up_observed"
