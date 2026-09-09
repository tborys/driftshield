"""A Codex tool call that reports a non zero exit code is a failed tool call.

Codex rollouts carry the exit code inside the output text (an ``exit=N`` line
or a JSON ``"exit_code": N`` field), and the older flat shape carries
``is_error`` / ``error`` on the tool output. Each of these must land on
``tool_activity.status == "error"`` so the existing failure rules see it and a
Codex run can fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield import analyse_run
from driftshield.core.analysis.tool_outcomes import (
    UNRECOVERED_TOOL_ERROR_AT_SESSION_END,
    final_tool_error,
)
from driftshield.core.models import EventType
from driftshield.parsers.codex_cli import CodexCliParser, parse_exit_code

FIXTURES = Path(__file__).parent.parent / "fixtures" / "transcripts"
EXIT_LINE_AT_END = FIXTURES / "sample_codex_cli_rollout_exit_code_at_end.jsonl"
EXIT_CODE_JSON = FIXTURES / "sample_codex_cli_rollout_exit_code_json.jsonl"
FLAT_IS_ERROR = FIXTURES / "sample_codex_cli_tool_error.jsonl"
ROLLOUT_CLEAN = FIXTURES / "sample_codex_cli_rollout.jsonl"


def _tool_events(events):
    return [e for e in events if e.event_type in {EventType.TOOL_CALL, EventType.HANDOFF}]


def _statuses(events):
    return [(e.tool_activity or {}).get("status") for e in _tool_events(events)]


def _rollout(lines: list[dict]) -> str:
    return "\n".join(json.dumps(line) for line in lines)


def _exec_call(call_id: str, command: str) -> dict:
    return {
        "timestamp": "2026-09-02T10:00:00Z",
        "type": "response_item",
        "payload": {"type": "custom_tool_call", "call_id": call_id, "name": "exec", "input": command},
    }


def _exec_output(call_id: str, *chunks: str) -> dict:
    return {
        "timestamp": "2026-09-02T10:00:01Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": [{"type": "input_text", "text": chunk} for chunk in chunks],
        },
    }


class TestParseExitCode:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("---0---\n\nexit=1", 1),
            ("Output:\nall good\n---0---\n\nexit=0", 0),
            ("---0---\nsignal\nexit=-9", -9),
            ('{"chunk_id":"e0209f","wall_time_seconds":0.0,"exit_code":0}', 0),
            ('{"chunk_id":"e0209f","wall_time_seconds":0.0,"exit_code":2}', 2),
            ("---0---\nexit=0\n---1---\nexit=3", 3),
        ],
    )
    def test_reads_a_clearly_stated_integer(self, text: str, expected: int):
        assert parse_exit_code(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "Error: something went wrong",
            "the process exited with an error",
            "exit=abc",
            "please exit=1 now",
            '"exit_code": "1"',
            "exit_code=1",
        ],
    )
    def test_never_guesses_from_words_or_loose_shapes(self, text: str):
        assert parse_exit_code(text) is None


class TestExitLineShape:
    def test_non_zero_exit_marks_the_call_as_error_and_keeps_the_exit_code(self):
        events = CodexCliParser().parse_file(str(EXIT_LINE_AT_END))
        passed, failed = _tool_events(events)

        assert _statuses(events) == ["completed", "error"]
        assert passed.failure_context is None
        assert passed.outputs["exit_code"] == 0
        assert failed.action == "exec"
        assert failed.failure_context["status"] == "error"
        assert failed.failure_context["exit_code"] == 1
        assert "tool_marked_error" in failed.failure_context["signals"]

    def test_failure_context_keeps_the_tail_of_the_output(self):
        events = CodexCliParser().parse_file(str(EXIT_LINE_AT_END))
        failed = _tool_events(events)[-1]

        assert failed.failure_context["error"].endswith("exit=1")
        assert "RuntimeError: version in pyproject.toml" in failed.failure_context["error"]
        assert failed.outputs["result"].startswith("Script completed")

    def test_session_ending_on_the_call_is_a_qualified_failure(self):
        run = analyse_run(EXIT_LINE_AT_END.read_bytes(), source=EXIT_LINE_AT_END.name)
        failed = _tool_events(run.events)[-1]
        break_point = run.analysis.candidate_break_point

        assert run.detected_format == "codex_cli"
        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]
        assert final_tool_error(run.events) is failed
        assert break_point.is_identified
        assert break_point.node_id == failed.id
        assert break_point.action == "exec"
        assert break_point.strategy == "final_tool_error"
        delta = run.canonical_analysis["expected_vs_actual_delta"]
        assert UNRECOVERED_TOOL_ERROR_AT_SESSION_END in delta["delta_types"]


class TestExitCodeJsonShape:
    def test_non_zero_exit_code_marks_the_call_as_error(self):
        events = CodexCliParser().parse_file(str(EXIT_CODE_JSON))
        passed, failed = _tool_events(events)

        assert _statuses(events) == ["completed", "error"]
        assert passed.outputs["exit_code"] == 0
        assert passed.failure_context is None
        assert failed.action == "exec_command"
        assert failed.failure_context["status"] == "error"
        assert failed.failure_context["exit_code"] == 2
        assert "hatchling is not installed" in failed.failure_context["error"]

    def test_session_ending_on_the_call_is_a_qualified_failure(self):
        run = analyse_run(EXIT_CODE_JSON.read_bytes(), source=EXIT_CODE_JSON.name)
        failed = _tool_events(run.events)[-1]

        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]
        assert run.analysis.candidate_break_point.node_id == failed.id
        assert run.analysis.candidate_break_point.action == "exec_command"


class TestFlatShapeIsError:
    def test_is_error_and_error_text_mark_the_call_as_error(self):
        events = CodexCliParser().parse_file(str(FLAT_IS_ERROR))
        (failed,) = _tool_events(events)

        assert failed.action == "shell"
        assert failed.tool_activity["status"] == "error"
        assert failed.failure_context["status"] == "error"
        assert failed.failure_context["error"] == "command exited with status 2"
        assert failed.failure_context["signals"] == ["explicit_error", "tool_marked_error"]
        assert failed.outputs["result"].startswith("make: *** No rule to make target")

    def test_is_error_alone_is_enough(self):
        content = "\n".join(
            [
                '{"session_id":"s","type":"message","role":"assistant",'
                '"tool_calls":[{"id":"t1","name":"shell","arguments":{"command":"x"}}]}',
                '{"session_id":"s","type":"message","role":"tool","tool_call_id":"t1",'
                '"result":"no such file","is_error":true}',
            ]
        )
        (failed,) = _tool_events(CodexCliParser().parse(content))

        assert failed.tool_activity["status"] == "error"
        assert failed.failure_context["signals"] == ["tool_marked_error"]

    def test_session_ending_on_the_call_is_a_qualified_failure(self):
        run = analyse_run(FLAT_IS_ERROR.read_bytes(), source=FLAT_IS_ERROR.name)
        (failed,) = _tool_events(run.events)

        assert run.detected_format == "codex_cli"
        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]
        assert run.analysis.candidate_break_point.node_id == failed.id


class TestExitZeroStaysCompleted:
    def test_clean_rollout_fixture_is_unchanged(self):
        run = analyse_run(ROLLOUT_CLEAN.read_bytes(), source=ROLLOUT_CLEAN.name)

        assert set(_statuses(run.events)) == {"completed"}
        assert run.qualification_state == "unclassified"
        assert run.qualification_reasons == ["no_material_delta_detected"]
        assert not run.analysis.candidate_break_point.is_identified

    def test_session_ending_on_exit_zero_is_not_a_failure(self):
        content = _rollout(
            [
                _exec_call("c1", "pytest -q"),
                _exec_output("c1", "Script completed\nOutput:\n", "---0---\n2 passed\n\nexit=0"),
            ]
        )
        run = analyse_run(content.encode("utf-8"), format="codex_cli")
        (call,) = _tool_events(run.events)

        assert call.tool_activity["status"] == "completed"
        assert call.outputs["exit_code"] == 0
        assert call.failure_context is None
        assert run.qualification_state == "unclassified"
        assert final_tool_error(run.events) is None

    def test_error_words_without_an_exit_code_do_not_fail_the_call(self):
        content = _rollout(
            [
                _exec_call("c1", "grep -rn error src"),
                _exec_output("c1", "src/app.py:3: raise RuntimeError('error handling')\n"),
            ]
        )
        run = analyse_run(content.encode("utf-8"), format="codex_cli")
        (call,) = _tool_events(run.events)

        assert call.tool_activity["status"] == "completed"
        assert "exit_code" not in call.outputs
        assert final_tool_error(run.events) is None
