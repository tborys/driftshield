"""A tool error the run never recovered counts as a failure.

Pins the failure signal for runs that carry no other risk evidence: the last
tool call reported an error and no later tool call completed. A failed tool
call is recovered only by evidence tied to it, a later completed call of the
same tool on the same command or target, and the recovering call is recorded
on the failed event as ``recovered_by``.
"""

from __future__ import annotations

import json
from pathlib import Path

from driftshield import analyse_run
from driftshield.core.analysis.inflection import UNRECOVERED_TOOL_ERROR_STRATEGY
from driftshield.core.analysis.tool_outcomes import (
    MATCHING_CALL_DID_NOT_COMPLETE,
    MATCHING_CALL_FAILED_AGAIN,
    NO_COMPARABLE_INPUT,
    NO_LATER_TOOL_CALL,
    NO_MATCHING_LATER_CALL,
    RECOVERED_SAME_COMMAND,
    RECOVERED_SAME_INPUT,
    RECOVERED_SAME_TARGET,
    UNRECOVERED_TOOL_ERROR_AT_SESSION_END,
    final_tool_error,
    first_unrecovered_tool_error,
    tool_failure_outcomes,
    unrecovered_tool_failure,
)
from driftshield.core.models import EventType

FIXTURES = Path(__file__).parent.parent / "fixtures" / "transcripts"
ERROR_AT_END = FIXTURES / "sample_claude_code_tool_error_at_end.jsonl"
RECOVERED = FIXTURES / "sample_claude_code_tool_error_recovered.jsonl"
SUCCESS = FIXTURES / "sample_claude_code_tool_success.jsonl"
UNRELATED_READ = FIXTURES / "sample_claude_code_tool_error_unrelated_read.jsonl"
FAILED_AGAIN = FIXTURES / "sample_claude_code_tool_error_failed_again.jsonl"
WRITE_RECOVERED = FIXTURES / "sample_claude_code_tool_error_write_recovered.jsonl"


def _claude_code(lines: list[dict]) -> bytes:
    return "\n".join(json.dumps(line) for line in lines).encode("utf-8")


def _tool_use(tool_id: str, name: str, ts: str, inputs: dict | None = None) -> dict:
    if inputs is None:
        inputs = {"command": "x"}
    return {
        "sessionId": "s1",
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": "c",
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inputs}],
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


def _tool_events(run):
    return [event for event in run.events if event.event_type is EventType.TOOL_CALL]


def _failed_tool_events(run):
    return [event for event in _tool_events(run) if event.tool_activity["status"] == "error"]


def _run(steps: list[tuple[str, str, dict | None, bool | None]]):
    """Build a run from (tool_id, tool_name, inputs, result) steps.

    ``result`` is ``True`` for a completed call, ``False`` for an error and
    ``None`` for a call that never returned.
    """
    lines: list[dict] = []
    for n, (tool_id, name, inputs, result) in enumerate(steps):
        lines.append(_tool_use(tool_id, name, f"2026-09-01T09:{n:02d}:00Z", inputs))
        if result is not None:
            lines.append(_tool_result(tool_id, f"2026-09-01T09:{n:02d}:01Z", is_error=not result))
    return analyse_run(_claude_code(lines), format="claude_code")


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

    def test_failed_test_rerun_and_passing_is_cited_as_recovered_by(self):
        # Same tool (Bash), same command: the rerun that passed is the evidence.
        run = analyse_run(RECOVERED.read_bytes(), source=RECOVERED.name)
        tools = _tool_events(run)
        failed, rerun = tools[1], tools[3]

        assert failed.inputs["command"] == rerun.inputs["command"]
        assert failed.tool_activity["recovered_by"] == str(rerun.id)
        assert failed.tool_activity["recovery_reason"] == RECOVERED_SAME_COMMAND
        assert "recovered_by" not in rerun.tool_activity
        assert unrecovered_tool_failure(run.events) is False
        assert first_unrecovered_tool_error(run.events) is None

    def test_failed_write_then_the_same_file_written_is_recovered(self):
        run = analyse_run(WRITE_RECOVERED.read_bytes(), source=WRITE_RECOVERED.name)
        tools = _tool_events(run)
        failed, rewrite = tools[0], tools[2]

        assert (failed.action, rewrite.action) == ("Write", "Write")
        assert failed.inputs["file_path"] == rewrite.inputs["file_path"]
        assert failed.tool_activity["recovered_by"] == str(rewrite.id)
        assert failed.tool_activity["recovery_reason"] == RECOVERED_SAME_TARGET
        assert unrecovered_tool_failure(run.events) is False
        assert run.qualification_state == "unclassified"
        assert run.qualification_reasons == ["no_material_delta_detected"]
        assert not run.analysis.candidate_break_point.is_identified


class TestUnrecoveredMidRunToolError:
    """A failed call the run carried on past without evidence tied to it."""

    def test_unrelated_successful_read_does_not_recover_a_failed_test(self):
        run = analyse_run(UNRELATED_READ.read_bytes(), source=UNRELATED_READ.name)
        [failed] = _failed_tool_events(run)

        assert failed.action == "Bash"
        assert failed.tool_activity["recovered_by"] is None
        assert failed.tool_activity["recovery_reason"] == NO_MATCHING_LATER_CALL
        assert unrecovered_tool_failure(run.events) is True
        assert first_unrecovered_tool_error(run.events) is failed
        assert final_tool_error(run.events) is None

    def test_unrelated_read_run_qualifies_under_the_material_delta_rule(self):
        run = analyse_run(UNRELATED_READ.read_bytes(), source=UNRELATED_READ.name)
        delta = run.canonical_analysis["expected_vs_actual_delta"]

        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == []
        assert delta["delta_types"] == ["tool_execution_failure"]
        assert UNRECOVERED_TOOL_ERROR_AT_SESSION_END not in delta["delta_types"]

    def test_unrelated_read_break_point_is_the_failed_call(self):
        run = analyse_run(UNRELATED_READ.read_bytes(), source=UNRELATED_READ.name)
        [failed] = _failed_tool_events(run)
        break_point = run.analysis.candidate_break_point

        assert break_point.is_identified
        assert break_point.node_id == failed.id
        assert break_point.action == "Bash"
        assert break_point.strategy == UNRECOVERED_TOOL_ERROR_STRATEGY
        assert NO_MATCHING_LATER_CALL in break_point.summary
        assert next(f for f in run.findings if f.kind == "break_point").event_id == str(failed.id)

    def test_incomplete_execution_record_points_at_the_unrecovered_call(self):
        run = analyse_run(UNRELATED_READ.read_bytes(), source=UNRELATED_READ.name)
        [failed] = _failed_tool_events(run)
        [record] = [r for r in run.canonical_analysis["delta_records"] if r["delta_type"] == "incomplete_execution"]

        assert record["expected_ref"] == str(failed.id)

    def test_same_test_failing_again_is_not_a_recovery(self):
        run = analyse_run(FAILED_AGAIN.read_bytes(), source=FAILED_AGAIN.name)
        first, second = _failed_tool_events(run)

        assert first.inputs["command"] == second.inputs["command"]
        assert first.tool_activity["recovered_by"] is None
        assert first.tool_activity["recovery_reason"] == MATCHING_CALL_FAILED_AGAIN
        assert second.tool_activity["recovered_by"] is None
        assert second.tool_activity["recovery_reason"] == NO_MATCHING_LATER_CALL
        assert run.qualification_state == "qualified_failure"
        assert run.canonical_analysis["expected_vs_actual_delta"]["delta_types"] == [
            "tool_execution_failure"
        ]

    def test_failed_again_break_point_is_the_first_unrecovered_call(self):
        run = analyse_run(FAILED_AGAIN.read_bytes(), source=FAILED_AGAIN.name)
        first, _ = _failed_tool_events(run)
        break_point = run.analysis.candidate_break_point

        assert first_unrecovered_tool_error(run.events) is first
        assert break_point.node_id == first.id
        assert break_point.strategy == UNRECOVERED_TOOL_ERROR_STRATEGY

    def test_session_end_rule_still_wins_when_the_run_ends_on_the_failure(self):
        run = analyse_run(ERROR_AT_END.read_bytes(), source=ERROR_AT_END.name)
        [failed] = _failed_tool_events(run)

        assert failed.tool_activity["recovered_by"] is None
        assert failed.tool_activity["recovery_reason"] == NO_LATER_TOOL_CALL
        assert run.analysis.candidate_break_point.strategy == "final_tool_error"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]


class TestRecoveryMatching:
    """What counts as the same command or target, decided from structured inputs."""

    def test_same_command_on_a_different_tool_does_not_recover(self):
        run = _run([("t1", "Bash", {"command": "pytest -q"}, False), ("t2", "Shell", {"command": "pytest -q"}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is False
        assert outcome.reason == NO_MATCHING_LATER_CALL

    def test_different_command_on_the_same_tool_does_not_recover(self):
        run = _run([("t1", "Bash", {"command": "pytest -q"}, False), ("t2", "Bash", {"command": "pytest -q -x"}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is False
        assert outcome.reason == NO_MATCHING_LATER_CALL

    def test_command_whitespace_is_not_a_difference(self):
        run = _run([("t1", "Bash", {"command": "pytest  -q "}, False), ("t2", "Bash", {"command": "pytest -q"}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is True
        assert outcome.recovered_by is _tool_events(run)[1]
        assert outcome.reason == RECOVERED_SAME_COMMAND

    def test_argv_style_command_matches_its_string_form(self):
        run = _run([("t1", "shell", {"command": ["pytest", "-q"]}, False), ("t2", "shell", {"command": "pytest -q"}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is True
        assert outcome.reason == RECOVERED_SAME_COMMAND

    def test_a_single_primary_argument_counts_as_the_target(self):
        run = _run([("t1", "Grep", {"pattern": "total("}, False), ("t2", "Grep", {"pattern": "total("}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is True
        assert outcome.reason == RECOVERED_SAME_INPUT

    def test_a_failed_call_without_comparable_inputs_stays_unrecovered(self):
        run = _run([("t1", "Bash", {}, False), ("t2", "Bash", {}, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is False
        assert outcome.reason == NO_COMPARABLE_INPUT
        assert unrecovered_tool_failure(run.events) is True

    def test_multi_key_inputs_without_a_known_target_key_are_not_matched(self):
        inputs = {"old_string": "a", "new_string": "b"}
        run = _run([("t1", "Patch", inputs, False), ("t2", "Patch", inputs, True)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is False
        assert outcome.reason == NO_COMPARABLE_INPUT

    def test_rerun_that_never_returned_does_not_recover(self):
        run = _run([("t1", "Bash", {"command": "pytest -q"}, False), ("t2", "Bash", {"command": "pytest -q"}, None)])
        [outcome] = tool_failure_outcomes(run.events)

        assert outcome.recovered is False
        assert outcome.reason == MATCHING_CALL_DID_NOT_COMPLETE

    def test_each_failure_needs_its_own_recovery(self):
        # The write is recovered, the test run never is: the run still fails.
        run = _run(
            [
                ("t1", "Bash", {"command": "pytest -q"}, False),
                ("t2", "Write", {"file_path": "/tmp/a.md", "content": "x"}, False),
                ("t3", "Write", {"file_path": "/tmp/a.md", "content": "x"}, True),
            ]
        )
        test_run, write = tool_failure_outcomes(run.events)

        assert test_run.recovered is False
        assert write.recovered is True
        assert first_unrecovered_tool_error(run.events) is test_run.failed
        assert run.qualification_state == "qualified_failure"

    def test_a_pass_between_two_failures_recovers_only_the_first(self):
        run = _run(
            [
                ("t1", "Bash", {"command": "pytest -q"}, False),
                ("t2", "Bash", {"command": "pytest -q"}, True),
                ("t3", "Bash", {"command": "pytest -q"}, False),
            ]
        )
        first, last = tool_failure_outcomes(run.events)

        assert first.recovered_by is _tool_events(run)[1]
        assert last.recovered is False
        assert last.reason == NO_LATER_TOOL_CALL
        assert final_tool_error(run.events) is last.failed


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

    def test_final_tool_error_is_none_when_the_same_call_later_completed(self):
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
        # The failed call is still the break point, under the mid-run strategy.
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
        assert run.analysis.candidate_break_point.strategy == UNRECOVERED_TOOL_ERROR_STRATEGY
