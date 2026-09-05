"""Structural tool outcome checks shared by analysis and qualification.

These predicates read the normalised tool outcome (``tool_activity.status`` /
``failure_context``) that normalisation derives from the run's own error flag.
They never key on scrubbed free text.
"""

from __future__ import annotations

from driftshield.core.models import CanonicalEvent, EventType

_TOOL_EVENT_TYPES = {EventType.TOOL_CALL, EventType.HANDOFF}

# Delta type and qualification reason for a run whose final tool call failed and
# was never followed by a completed tool call. Both are the same string so the
# verdict and the delta explain themselves with one vocabulary.
UNRECOVERED_TOOL_ERROR_AT_SESSION_END = "unrecovered_tool_error_at_session_end"


def is_tool_event(event: CanonicalEvent) -> bool:
    return event.event_type in _TOOL_EVENT_TYPES


def is_failed_tool_event(event: CanonicalEvent) -> bool:
    """A tool/handoff call the run itself reported as failed.

    An aborted or timed-out model turn lands on an OUTPUT/system event, not a
    tool event, so it is not counted here.
    """
    if not is_tool_event(event):
        return False
    if (event.tool_activity or {}).get("status") == "error":
        return True
    return bool(event.failure_context and event.failure_context.get("status") == "error")


def is_completed_tool_event(event: CanonicalEvent) -> bool:
    return (
        is_tool_event(event)
        and not is_failed_tool_event(event)
        and (event.tool_activity or {}).get("status") == "completed"
    )


def unrecovered_tool_failure(events: list[CanonicalEvent]) -> bool:
    """True when a failed tool call was not followed by a recovering tool call.

    A failed tool the run recovered from is not a material delta, but recovery
    needs structural evidence: a later tool that actually *completed*
    (``tool_activity.status == "completed"``), not merely a later tool that was
    present. A trajectory's successful toolMetas normalise to ``pending`` (the
    runtime carries no per-tool result body), so a failed trajectory tool
    followed by more pending tools is still an unrecovered failure, not a
    recovery.
    """
    last_failure_index: int | None = None
    for index, event in enumerate(events):
        if is_failed_tool_event(event):
            last_failure_index = index
    if last_failure_index is None:
        return False
    return not any(is_completed_tool_event(event) for event in events[last_failure_index + 1 :])


def final_tool_error(events: list[CanonicalEvent]) -> CanonicalEvent | None:
    """The last tool call of the run, when it reported an error nobody recovered.

    The session ends on a failed tool call: no later tool call exists, so no
    later tool call can have completed. This is the failure signal for runs that
    carry no other risk evidence. A failed tool call that a later completed tool
    call recovers is not returned.
    """
    last_tool = next((event for event in reversed(events) if is_tool_event(event)), None)
    if last_tool is None or not is_failed_tool_event(last_tool):
        return None
    return last_tool
