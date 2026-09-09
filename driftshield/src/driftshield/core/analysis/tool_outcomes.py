"""Structural tool outcome checks shared by analysis and qualification.

These predicates read the normalised tool outcome (``tool_activity.status`` /
``failure_context``) that normalisation derives from the run's own error flag.
They never key on scrubbed free text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from driftshield.core.models import CanonicalEvent, EventType

_TOOL_EVENT_TYPES = {EventType.TOOL_CALL, EventType.HANDOFF}

# Delta type and qualification reason for a run whose final tool call failed and
# was never followed by a completed tool call. Both are the same string so the
# verdict and the delta explain themselves with one vocabulary.
UNRECOVERED_TOOL_ERROR_AT_SESSION_END = "unrecovered_tool_error_at_session_end"

# Keys ``annotate_tool_recoveries`` writes into ``tool_activity`` on a failed
# tool event. ``recovered_by`` is the id of the recovering event, or ``None``.
# ``recovery_reason`` says what the evidence was, or why there is none.
RECOVERED_BY_KEY = "recovered_by"
RECOVERY_REASON_KEY = "recovery_reason"

# Recovery evidence kinds: a later completed call of the same tool that matched
# the failed call on this part of its inputs.
RECOVERED_SAME_COMMAND = "same_tool_same_command"
RECOVERED_SAME_TARGET = "same_tool_same_target"
RECOVERED_SAME_INPUT = "same_tool_same_input"

# Reason codes for a failed tool call that stays unrecovered.
NO_LATER_TOOL_CALL = "no_later_tool_call"
NO_COMPARABLE_INPUT = "no_comparable_input"
NO_MATCHING_LATER_CALL = "no_matching_later_call"
MATCHING_CALL_FAILED_AGAIN = "matching_call_failed_again"
MATCHING_CALL_DID_NOT_COMPLETE = "matching_call_did_not_complete"

# Structured input keys, in priority order, that identify what a tool call acted
# on. The target keys mirror normalisation's artifact keys minus ``cwd``, which
# is where a call ran, not what it acted on.
_COMMAND_KEYS = ("command", "cmd")
_TARGET_KEYS = ("file_path", "path", "target_path", "output_path", "source_path")
_PRIMARY_INPUT_KEYS = ("pattern", "query", "url")


@dataclass(frozen=True)
class ToolFailureOutcome:
    """Whether one failed tool call was recovered, and by what evidence."""

    failed: CanonicalEvent
    recovered_by: CanonicalEvent | None
    reason: str

    @property
    def recovered(self) -> bool:
        return self.recovered_by is not None


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


def _scalar_text(value: Any) -> str | None:
    """A comparable string for a command or path input, or ``None``.

    Strings collapse internal whitespace. A list of strings (a Codex ``shell``
    argv) joins into one string first. Anything else is not comparable.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        value = " ".join(value)
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def call_target(event: CanonicalEvent) -> tuple[str, str] | None:
    """What a tool call acted on, from its structured inputs, or ``None``.

    Returns ``(evidence_kind, value)``: the command string, else the file path,
    else the primary input argument (``pattern`` / ``query`` / ``url``, or the
    single scalar input when the call has exactly one). A call whose inputs
    carry none of these has no comparable target, so no later call can be
    matched to it.
    """
    inputs = event.inputs or {}
    if not isinstance(inputs, dict):
        return None
    for key in _COMMAND_KEYS:
        text = _scalar_text(inputs.get(key))
        if text is not None:
            return RECOVERED_SAME_COMMAND, text
    for key in _TARGET_KEYS:
        text = _scalar_text(inputs.get(key))
        if text is not None:
            return RECOVERED_SAME_TARGET, text
    for key in _PRIMARY_INPUT_KEYS:
        text = _scalar_text(inputs.get(key))
        if text is not None:
            return RECOVERED_SAME_INPUT, f"{key}={text}"
    if len(inputs) == 1:
        key, value = next(iter(inputs.items()))
        text = _scalar_text(value)
        if text is not None:
            return RECOVERED_SAME_INPUT, f"{key}={text}"
    return None


def _resolve_failure(events: list[CanonicalEvent], index: int) -> ToolFailureOutcome:
    failed = events[index]
    later_tools = [event for event in events[index + 1 :] if is_tool_event(event)]
    if not later_tools:
        return ToolFailureOutcome(failed, None, NO_LATER_TOOL_CALL)

    target = call_target(failed)
    if target is None:
        return ToolFailureOutcome(failed, None, NO_COMPARABLE_INPUT)

    matching = [
        event
        for event in later_tools
        if event.action == failed.action and call_target(event) == target
    ]
    if not matching:
        return ToolFailureOutcome(failed, None, NO_MATCHING_LATER_CALL)

    recovering = next((event for event in matching if is_completed_tool_event(event)), None)
    if recovering is not None:
        return ToolFailureOutcome(failed, recovering, target[0])
    if any(is_failed_tool_event(event) for event in matching):
        return ToolFailureOutcome(failed, None, MATCHING_CALL_FAILED_AGAIN)
    return ToolFailureOutcome(failed, None, MATCHING_CALL_DID_NOT_COMPLETE)


def tool_failure_outcomes(events: list[CanonicalEvent]) -> list[ToolFailureOutcome]:
    """One outcome per failed tool call, in run order.

    A failed call is recovered only by evidence tied to it: a later tool call
    that *completed* (``tool_activity.status == "completed"``), ran the same
    tool, and acted on the same command or target (the failed test rerun and
    passing, the file that failed to write written). Any other later call,
    however successful, leaves the failure unrecovered with a reason code.

    The match is deliberately conservative. A failed call whose inputs carry no
    command, path or primary argument cannot be matched, so it stays
    unrecovered (``no_comparable_input``) rather than being cleared. A
    trajectory's successful toolMetas normalise to ``pending`` (the runtime
    carries no per-tool result body), so a rerun that never completed does not
    recover anything either.
    """
    return [
        _resolve_failure(events, index)
        for index, event in enumerate(events)
        if is_failed_tool_event(event)
    ]


def annotate_tool_recoveries(events: list[CanonicalEvent]) -> None:
    """Record each failed tool call's recovery outcome on its ``tool_activity``.

    Writes ``recovered_by`` (the recovering event's id, or ``None``) and
    ``recovery_reason`` so a report can cite the recovering call, or say why
    none counted, instead of asserting recovery.
    """
    for outcome in tool_failure_outcomes(events):
        activity = outcome.failed.tool_activity
        if activity is None:
            activity = {}
            outcome.failed.tool_activity = activity
        activity[RECOVERED_BY_KEY] = (
            str(outcome.recovered_by.id) if outcome.recovered_by is not None else None
        )
        activity[RECOVERY_REASON_KEY] = outcome.reason


def unrecovered_tool_failures(events: list[CanonicalEvent]) -> list[CanonicalEvent]:
    """The failed tool calls no later matching completed call recovered, in run order."""
    return [outcome.failed for outcome in tool_failure_outcomes(events) if not outcome.recovered]


def unrecovered_tool_failure(events: list[CanonicalEvent]) -> bool:
    """True when at least one failed tool call was never recovered.

    See ``tool_failure_outcomes`` for what counts as recovery.
    """
    return bool(unrecovered_tool_failures(events))


def first_unrecovered_tool_error(events: list[CanonicalEvent]) -> CanonicalEvent | None:
    """The earliest failed tool call the run never recovered, or ``None``.

    This is the candidate break point for a run that carried on past a failure
    without evidence tied to it. When the run ends on a failed call,
    ``final_tool_error`` names that call instead.
    """
    unrecovered = unrecovered_tool_failures(events)
    return unrecovered[0] if unrecovered else None


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
