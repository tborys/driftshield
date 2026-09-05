"""A tool error never recovered before the session ends counts as a failure.

Pins the failure signal for runs that carry no other risk evidence: the last
tool call reported an error and no later tool call completed. A failed tool
call that a later completed tool call recovers is not a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from driftshield import analyse_run
from driftshield.core.analysis.tool_outcomes import (
    UNRECOVERED_TOOL_ERROR_AT_SESSION_END,
    final_tool_error,
    unrecovered_tool_failure,
)
from driftshield.core.models import EventType

FIXTURES = Path(__file__).parent.parent / "fixtures" / "transcripts"
ERROR_AT_END = FIXTURES / "sample_claude_code_tool_error_at_end.jsonl"
RECOVERED = FIXTURES / "sample_claude_code_tool_error_recovered.jsonl"
SUCCESS = FIXTURES / "sample_claude_code_tool_success.jsonl"


def _claude_code(lines: list[dict]) -> bytes:
    return "\n".join(json.dumps(line) for line in lines).encode("utf-8")


def _tool_use(tool_id: str, name: str, ts: str) -> dict:
    return {
        "sessionId": "s1",
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": "c",
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {"command": "x"}}],
        },
    }


def _tool_result(tool_id: str, ts: str, *, is_error: bool = False) -> dict:
    item = {"type": "tool_result", "tool_use_id": tool_id, "content": "out"}
    if is_error:
        item["is_error"] = True
    return {"sessionId": "s1", "type": "user", "timestamp": ts, "message": {"role": "user", "content": [item]}}


def _last_tool_event(run):
    return next(
        event
        for event in reversed(run.events)
        if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF}
    )


class TestSessionEndsOnToolError:
    def test_qualifies_with_the_session_end_reason(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)

        assert run.detected_format == "claude_code"
        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]

    def test_emits_its_own_delta_type(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)
        delta = run.canonical_analysis["expected_vs_actual_delta"]

        assert delta["delta_present"] is True
        assert UNRECOVERED_TOOL_ERROR_AT_SESSION_END in delta["delta_types"]
        assert delta["blocked_goal_summary"] == run.analysis.candidate_break_point.summary

    def test_break_point_is_the_final_failed_tool_call(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)
        break_point = run.analysis.candidate_break_point
        failed = _last_tool_event(run)

        assert failed.action == "Bash"
        assert break_point.is_identified
        assert break_point.node_id == failed.id
        assert break_point.action == "Bash"
        assert break_point.strategy == "final_tool_error"
        assert break_point.confidence == 1.0
        assert [f for f in run.findings if f.kind == "break_point"][0].event_id == str(failed.id)

    def test_no_heuristic_flag_is_needed(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)

        assert run.analysis.flagged_events == 0
        assert run.qualification_state == "qualified_failure"


class TestRecoveredToolError:
    def test_failure_followed_by_completed_tool_stays_unclassified(self):
        run = analyse_run(RECOVERED.read_bytes(), source=RECOVERED.name)

        assert run.qualification_state == "unclassified"
        assert run.qualification_reasons == ["no_material_delta_detected"]
        assert run.canonical_analysis["expected_vs_actual_delta"]["delta_types"] == [
            "no_material_delta_detected"
        ]
        assert not run.analysis.candidate_break_point.is_identified

    def test_recovered_run_still_records_the_failed_tool_in_events(self):
        run = analyse_run(RECOVERED.read_bytes(), source=RECOVERED.name)
        statuses = [
            (event.tool_activity or {}).get("status")
            for event in run.events
            if event.event_type is EventType.TOOL_CALL
        ]
        assert statuses == ["completed", "error", "completed", "completed"]


class TestSuccessfulRun:
    def test_success_stays_unclassified(self):
        run = analyse_run(SUCCESS.read_bytes(), source=SUCCESS.name)

        assert run.qualification_state == "unclassified"
        assert run.qualification_reasons == ["no_material_delta_detected"]
        assert not run.analysis.candidate_break_point.is_identified


class TestToolOutcomePredicates:
    def test_final_tool_error_returns_the_last_tool_when_it_failed(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)
        assert final_tool_error(run.events) is _last_tool_event(run)
        assert unrecovered_tool_failure(run.events) is True

    def test_final_tool_error_is_none_when_a_later_tool_completed(self):
        run = analyse_run(RECOVERED.read_bytes(), source=RECOVERED.name)
        assert final_tool_error(run.events) is None
        assert unrecovered_tool_failure(run.events) is False

    def test_final_tool_error_is_none_without_any_failure(self):
        run = analyse_run(SUCCESS.read_bytes(), source=SUCCESS.name)
        assert final_tool_error(run.events) is None
        assert unrecovered_tool_failure(run.events) is False

    def test_failure_then_pending_tool_is_unrecovered_but_not_session_end(self):
        # A pending trailing tool (no result body) is not a completed recovery, so
        # the general rule still fires, but the session did not end on the error.
        run = analyse_run(
            _claude_code(
                [
                    _tool_use("t1", "Bash", "2026-09-01T09:00:00Z"),
                    _tool_result("t1", "2026-09-01T09:00:01Z", is_error=True),
                    _tool_use("t2", "Bash", "2026-09-01T09:00:02Z"),
                ]
            ),
            format="claude_code",
        )
        delta_types = run.canonical_analysis["expected_vs_actual_delta"]["delta_types"]

        assert final_tool_error(run.events) is None
        assert unrecovered_tool_failure(run.events) is True
        assert "tool_execution_failure" in delta_types
        assert UNRECOVERED_TOOL_ERROR_AT_SESSION_END not in delta_types
        assert run.qualification_reasons == []
