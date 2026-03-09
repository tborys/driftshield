from datetime import datetime, timezone, timedelta
from uuid import uuid4

from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import CanonicalEvent, EventType


def make_event(*, action: str, event_type: EventType, agent_id: str, inputs=None, outputs=None, parent_event_id=None, timestamp=None):
    return CanonicalEvent(
        id=uuid4(),
        session_id="assumption-mutation-test",
        timestamp=timestamp or datetime.now(timezone.utc),
        event_type=event_type,
        agent_id=agent_id,
        action=action,
        parent_event_id=parent_event_id,
        inputs=inputs or {},
        outputs=outputs or {},
        metadata={},
    )


def test_flags_when_assistant_introduced_assumption_drives_new_plan_step():
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    narrative = make_event(
        action="assistant_narrative",
        event_type=EventType.OUTPUT,
        agent_id="claude",
        outputs={"text": "I'll assume a weekday launch and move on to the rollout schedule."},
        timestamp=t0,
    )
    plan_step = make_event(
        action="plan_schedule",
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        inputs={"assumption": "weekday launch"},
        parent_event_id=narrative.id,
        timestamp=t0 + timedelta(seconds=1),
    )

    result = analyze_session([narrative, plan_step])

    flagged_event = result.events[-1]
    assert flagged_event.risk_classification is not None
    assert flagged_event.risk_classification.assumption_mutation is True


def test_does_not_flag_when_user_explicitly_requests_the_same_plan_change():
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    user_instruction = make_event(
        action="user_message",
        event_type=EventType.OUTPUT,
        agent_id="user",
        outputs={"text": "Please assume a weekday launch and build the rollout schedule around that."},
        timestamp=t0,
    )
    assistant_narrative = make_event(
        action="assistant_narrative",
        event_type=EventType.OUTPUT,
        agent_id="claude",
        outputs={"text": "I'll use the weekday launch assumption when planning the schedule."},
        parent_event_id=user_instruction.id,
        timestamp=t0 + timedelta(seconds=1),
    )
    plan_step = make_event(
        action="plan_schedule",
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        inputs={"assumption": "weekday launch"},
        parent_event_id=assistant_narrative.id,
        timestamp=t0 + timedelta(seconds=2),
    )

    result = analyze_session([user_instruction, assistant_narrative, plan_step])

    flagged_event = result.events[-1]
    assert flagged_event.risk_classification is None or not flagged_event.risk_classification.assumption_mutation
