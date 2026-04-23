"""Reusable lineage fixtures for Phase 2b graph coverage."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType


def _ts(step: int) -> datetime:
    base = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=step)


def linear_lineage_events(session_id: str = "lineage-linear-001") -> list[CanonicalEvent]:
    root = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(0),
        event_type=EventType.TOOL_CALL,
        agent_id="analyst",
        action="load_session",
        outputs={"status": "loaded"},
    )
    inspect = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(1),
        event_type=EventType.TOOL_CALL,
        agent_id="analyst",
        action="inspect_failure",
        parent_event_id=root.id,
        inputs={"session_id": session_id},
        outputs={"status": "reviewed"},
    )
    conclude = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(2),
        event_type=EventType.OUTPUT,
        agent_id="analyst",
        action="draft_summary",
        parent_event_id=inspect.id,
        outputs={"summary": "Failure path reconstructed"},
    )
    return [root, inspect, conclude]


def branching_lineage_events(session_id: str = "lineage-branching-001") -> list[CanonicalEvent]:
    root = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(0),
        event_type=EventType.TOOL_CALL,
        agent_id="analyst",
        action="load_session",
        outputs={"status": "loaded"},
    )
    branch_a = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(1),
        event_type=EventType.BRANCH,
        agent_id="analyst",
        action="review_tool_trace",
        parent_event_id=root.id,
        outputs={"hypothesis": "Tool path may have diverged"},
    )
    branch_b = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(2),
        event_type=EventType.TOOL_CALL,
        agent_id="analyst",
        action="review_user_constraints",
        parent_event_id=root.id,
        inputs={"focus": "constraint handling"},
        outputs={"hypothesis": "User guardrails were underspecified"},
    )
    merge = CanonicalEvent(
        id=uuid4(),
        session_id=session_id,
        timestamp=_ts(3),
        event_type=EventType.OUTPUT,
        agent_id="analyst",
        action="synthesize_findings",
        parent_event_refs=[branch_a.id, branch_b.id],
        outputs={"summary": "Combined tool and constraint evidence into one narrative"},
    )
    return [root, branch_a, branch_b, merge]
