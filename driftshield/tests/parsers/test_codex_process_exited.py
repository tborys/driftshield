"""A Codex shell call whose output says ``Process exited with code N``.

``exec_command`` and ``write_stdin`` outputs state the exit code on a line of
their own, ``Process exited with code N``, not in the ``exit=N`` or JSON
``"exit_code": N`` shapes. A non zero code on that line is a failed tool call,
exactly like the other shapes, so the session end and recovery rules see it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield import analyse_run
from driftshield.core.analysis.tool_outcomes import (
    MATCHING_CALL_FAILED_AGAIN,
    NO_MATCHING_LATER_CALL,
    RECOVERED_SAME_COMMAND,
    UNRECOVERED_TOOL_ERROR_AT_SESSION_END,
    call_target,
    final_tool_error,
    first_unrecovered_tool_error,
    unrecovered_tool_failure,
)
from driftshield.core.models import EventType
from driftshield.parsers.codex_cli import CodexCliParser, parse_exit_code

FIXTURES = Path(__file__).parent.parent / "fixtures" / "transcripts"
PROCESS_EXITED = FIXTURES / "sample_codex_cli_rollout_process_exited.jsonl"
LINE_LAST = FIXTURES / "sample_codex_cli_rollout_process_exited_last_line.jsonl"
PYTEST_RERUN = FIXTURES / "sample_codex_cli_rollout_process_exited_pytest_rerun.jsonl"


def _tool_events(events):
    return [e for e in events if e.event_type in {EventType.TOOL_CALL, EventType.HANDOFF}]


def _statuses(events):
    return [(e.tool_activity or {}).get("status") for e in _tool_events(events)]


_SESSION_META = {
    "timestamp": "2026-09-11T09:00:00Z",
    "type": "session_meta",
    "payload": {"id": "codex-process-exited", "cwd": "/workspace/project"},
}


def _rollout(lines: list[dict]) -> str:
    return "\n".join(json.dumps(line) for line in [_SESSION_META, *lines])


def _exec_command(call_id: str, cmd: str, minute: int) -> dict:
    return {
        "timestamp": f"2026-09-11T09:{minute:02d}:00Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "arguments": json.dumps({"cmd": cmd, "workdir": "/workspace/project", "yield_time_ms": 10000}),
            "call_id": call_id,
        },
    }


def _exec_command_output(call_id: str, exit_code: int, body: str, minute: int) -> dict:
    return {
        "timestamp": f"2026-09-11T09:{minute:02d}:01Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": (
                f"Chunk ID: c{minute:05d}\nWall time: 0.4 seconds\n"
                f"Process exited with code {exit_code}\nOriginal token count: 12\nOutput:\n{body}"
            ),
        },
    }


class TestParseProcessExitedLine:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Process exited with code 1", 1),
            ("Process exited with code 0", 0),
            ("Process exited with code -9", -9),
            (
                (
                    "Chunk ID: 3f9a01\nWall time: 0.0412 seconds\nProcess exited with code 128\n"
                    "Original token count: 9\nOutput:\nfatal: not a git repository\n"
                ),
                128,
            ),
            ("Output:\n" + "building\n" * 50 + "Process exited with code 2\n", 2),
        ],
    )
    def test_reads_the_whole_line(self, text: str, expected: int):
        assert parse_exit_code(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "process exited with code 1",
            "The process exited with code 1",
            "Error: Process exited with code 1",
            "  Process exited with code 1",
            "Process exited with code 1.",
            "Process exited with code 1 after 3 retries",
            "Process exited with code one",
            "Process exited with code",
            "Process running with session ID 4711",
            '{"output": "Process exited with code 1"}',
            "Error: the command failed with an error",
        ],
    )
    def test_never_guesses_from_words_or_loose_shapes(self, text: str):
        assert parse_exit_code(text) is None


class TestPrecedence:
    def test_the_first_process_exited_line_wins(self):
        text = (
            "Chunk ID: a1\nWall time: 0.1 seconds\nProcess exited with code 1\n"
            "Original token count: 30\nOutput:\n$ tail run.log\nProcess exited with code 0\n"
        )

        assert parse_exit_code(text) == 1

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Process exited with code 1\nOutput:\n---0---\nexit=0", 0),
            ('Process exited with code 3\nOutput:\n{"chunk_id": "a1", "exit_code": 0}', 0),
        ],
    )
    def test_the_older_shapes_keep_their_exit_code_when_both_appear(self, text: str, expected: int):
        assert parse_exit_code(text) == expected


class TestExitCodes:
    def test_exit_zero_stays_completed_and_non_zero_marks_the_call_failed(self):
        events = CodexCliParser().parse_file(str(PROCESS_EXITED))
        passed, failed = _tool_events(events)

        assert _statuses(events) == ["completed", "error"]
        assert passed.outputs["exit_code"] == 0
        assert passed.failure_context is None
        assert failed.action == "exec_command"
        assert failed.inputs["command"] == "mypy src"
        assert failed.outputs["exit_code"] == 1
        assert failed.failure_context["status"] == "error"
        assert failed.failure_context["exit_code"] == 1
        assert "tool_marked_error" in failed.failure_context["signals"]
        assert failed.failure_context["error"].endswith("Found 1 error in 1 file (checked 6 source files)")

    def test_session_ending_on_the_call_is_a_qualified_failure(self):
        run = analyse_run(PROCESS_EXITED.read_bytes(), source=PROCESS_EXITED.name)
        failed = _tool_events(run.events)[-1]
        break_point = run.analysis.candidate_break_point

        assert run.detected_format == "codex_cli"
        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]
        assert final_tool_error(run.events) is failed
        assert break_point.is_identified
        assert break_point.node_id == failed.id
        assert break_point.action == "exec_command"
        assert break_point.strategy == "final_tool_error"

    def test_session_ending_on_exit_zero_is_not_a_failure(self):
        content = _rollout(
            [
                _exec_command("c1", "pytest -q", 0),
                _exec_command_output("c1", 0, "3 passed in 0.4s\n", 0),
            ]
        )
        run = analyse_run(content.encode("utf-8"), format="codex_cli")
        (call,) = _tool_events(run.events)

        assert call.tool_activity["status"] == "completed"
        assert call.outputs["exit_code"] == 0
        assert call.failure_context is None
        assert run.qualification_state == "unclassified"
        assert final_tool_error(run.events) is None


class TestLineAfterALongOutput:
    def test_the_line_at_the_end_marks_the_call_failed_with_the_output_tail(self):
        events = CodexCliParser().parse_file(str(LINE_LAST))
        start, poll = _tool_events(events)

        assert start.tool_activity["status"] == "completed"
        assert "exit_code" not in start.outputs
        assert poll.action == "write_stdin"
        assert poll.tool_activity["status"] == "error"
        assert poll.failure_context["exit_code"] == 2
        result = poll.outputs["result"]
        tail = poll.failure_context["error"]
        assert len(result) > 400
        assert len(tail) <= 400
        assert tail.endswith("make: *** [build] Error 2\nProcess exited with code 2")
        assert result.startswith("Chunk ID: 5b7e20") and not tail.startswith("Chunk ID")

    def test_session_ending_on_the_call_is_a_qualified_failure(self):
        run = analyse_run(LINE_LAST.read_bytes(), source=LINE_LAST.name)
        poll = _tool_events(run.events)[-1]

        assert run.qualification_state == "qualified_failure"
        assert run.qualification_reasons == [UNRECOVERED_TOOL_ERROR_AT_SESSION_END]
        assert final_tool_error(run.events) is poll
        assert run.analysis.candidate_break_point.node_id == poll.id
        assert run.analysis.candidate_break_point.action == "write_stdin"


class TestRecovery:
    def test_failed_pytest_then_the_same_pytest_passing_is_recovered(self):
        run = analyse_run(PYTEST_RERUN.read_bytes(), source=PYTEST_RERUN.name)
        failed, patch, rerun = _tool_events(run.events)

        assert run.detected_format == "codex_cli"
        assert failed.action == rerun.action == "exec_command"
        assert failed.tool_activity["status"] == "error"
        assert failed.failure_context["exit_code"] == 1
        assert patch.inputs["file_path"] == "src/config.py"
        assert rerun.tool_activity["status"] == "completed"
        assert rerun.outputs["exit_code"] == 0
        assert call_target(failed) == call_target(rerun) == (RECOVERED_SAME_COMMAND, "pytest -q tests/test_config.py")
        assert failed.tool_activity["recovered_by"] == str(rerun.id)
        assert failed.tool_activity["recovery_reason"] == RECOVERED_SAME_COMMAND
        assert unrecovered_tool_failure(run.events) is False
        assert run.qualification_state == "unclassified"

    def test_failed_call_then_an_unrelated_call_stays_unrecovered(self):
        content = _rollout(
            [
                _exec_command("c1", "pytest -q tests/test_config.py", 0),
                _exec_command_output("c1", 1, "1 failed in 0.3s\n", 0),
                _exec_command("c2", "ls src", 1),
                _exec_command_output("c2", 0, "config.py\n", 1),
            ]
        )
        run = analyse_run(content.encode("utf-8"), format="codex_cli")
        failed, unrelated = _tool_events(run.events)

        assert failed.tool_activity["status"] == "error"
        assert unrelated.tool_activity["status"] == "completed"
        assert failed.tool_activity["recovered_by"] is None
        assert failed.tool_activity["recovery_reason"] == NO_MATCHING_LATER_CALL
        assert first_unrecovered_tool_error(run.events) is failed
        assert run.qualification_state == "qualified_failure"
        assert run.analysis.candidate_break_point.node_id == failed.id

    def test_the_same_command_failing_again_is_not_recovery(self):
        content = _rollout(
            [
                _exec_command("c1", "pytest -q tests/test_config.py", 0),
                _exec_command_output("c1", 1, "1 failed in 0.3s\n", 0),
                _exec_command("c2", "pytest -q tests/test_config.py", 1),
                _exec_command_output("c2", 1, "1 failed in 0.3s\n", 1),
            ]
        )
        run = analyse_run(content.encode("utf-8"), format="codex_cli")
        failed, again = _tool_events(run.events)

        assert _statuses(run.events) == ["error", "error"]
        assert failed.tool_activity["recovered_by"] is None
        assert failed.tool_activity["recovery_reason"] == MATCHING_CALL_FAILED_AGAIN
        assert final_tool_error(run.events) is again
        assert run.qualification_state == "qualified_failure"
