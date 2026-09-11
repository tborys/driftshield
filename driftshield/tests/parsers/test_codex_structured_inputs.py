"""A Codex tool call carries the structured inputs the recovery matcher reads.

A rollout states a call's command or target in its own shapes: a JSON string
argument (``exec_command``'s ``cmd``), a code mode ``exec`` script that calls
one tool, an ``apply_patch`` body. The rollout parser fills ``command``,
``file_path`` / ``file_paths`` and ``query`` from them, so same command or
target recovery and tool class checks work on Codex runs too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield import analyse_run
from driftshield.core.analysis.tool_outcomes import (
    NO_MATCHING_LATER_CALL,
    RECOVERED_SAME_COMMAND,
    RECOVERED_SAME_INPUT,
    RECOVERED_SAME_TARGET,
    call_target,
    first_unrecovered_tool_error,
    unrecovered_tool_failure,
)
from driftshield.core.models import EventType
from driftshield.parsers.codex_cli import CodexCliParser, code_mode_inputs, patch_file_paths

FIXTURES = Path(__file__).parent.parent / "fixtures" / "transcripts"
PYTEST_RERUN = FIXTURES / "sample_codex_cli_rollout_pytest_rerun.jsonl"
JSON_ARGUMENTS = FIXTURES / "sample_codex_cli_rollout_json_arguments.jsonl"
APPLY_PATCH = FIXTURES / "sample_codex_cli_rollout_apply_patch.jsonl"


def _tool_events(events):
    return [e for e in events if e.event_type in {EventType.TOOL_CALL, EventType.HANDOFF}]


def _by_action(events, action):
    return [e for e in _tool_events(events) if e.action == action]


_SESSION_META = {
    "timestamp": "2026-09-10T12:00:00Z",
    "type": "session_meta",
    "payload": {"id": "codex-structured-inputs", "cwd": "/workspace/project"},
}


def _rollout(lines: list[dict]) -> str:
    return "\n".join(json.dumps(line) for line in [_SESSION_META, *lines])


def _function_call(call_id: str, name: str, arguments: str) -> dict:
    return {
        "timestamp": "2026-09-10T12:00:00Z",
        "type": "response_item",
        "payload": {"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id},
    }


def _exec(call_id: str, command: str, minute: int) -> dict:
    return {
        "timestamp": f"2026-09-10T12:{minute:02d}:00Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": call_id,
            "name": "exec",
            "input": f"text(await tools.exec_command({{cmd:{json.dumps(command)}}}));\n",
        },
    }


def _exec_output(call_id: str, body: str, exit_code: int, minute: int) -> dict:
    return {
        "timestamp": f"2026-09-10T12:{minute:02d}:01Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": [
                {"type": "input_text", "text": "Script completed\nWall time 0.5 seconds\nOutput:\n"},
                {"type": "input_text", "text": f"---0---\n{body}\n\nexit={exit_code}"},
            ],
        },
    }


class TestJsonStringArguments:
    def test_exec_command_cmd_is_also_the_command(self):
        events = CodexCliParser().parse_file(str(JSON_ARGUMENTS))
        lint = _by_action(events, "exec_command")[0]

        assert lint.inputs["cmd"] == "ruff check src"
        assert lint.inputs["command"] == "ruff check src"
        assert lint.inputs["workdir"] == "/workspace/project"
        assert lint.tool_activity["category"] == "shell"
        assert call_target(lint) == (RECOVERED_SAME_COMMAND, "ruff check src")

    def test_exec_function_call_with_a_json_string_argument_carries_the_command(self):
        content = _rollout([_function_call("c1", "exec", '{"cmd": "npm test", "workdir": "/w"}')])
        (call,) = _tool_events(CodexCliParser().parse(content))

        assert call.inputs == {"cmd": "npm test", "workdir": "/w", "command": "npm test"}

    def test_file_tools_carry_file_path(self):
        events = CodexCliParser().parse_file(str(JSON_ARGUMENTS))
        (read,) = _by_action(events, "read_file")
        (write,) = _by_action(events, "write_file")

        assert read.inputs == {"path": "pyproject.toml", "file_path": "pyproject.toml"}
        assert write.inputs["file_path"] == "notes/lint.md"
        assert write.inputs["text"] == "Lint is clean.\n"
        assert call_target(write) == (RECOVERED_SAME_TARGET, "notes/lint.md")

    def test_run_with_one_search_query_carries_the_query(self):
        events = CodexCliParser().parse_file(str(JSON_ARGUMENTS))
        (search,) = _by_action(events, "run")

        assert search.inputs["query"] == "ruff rule E501 line length"
        assert call_target(search) == (RECOVERED_SAME_INPUT, "query=ruff rule E501 line length")

    def test_run_with_several_search_queries_gets_no_query(self):
        arguments = json.dumps({"search_query": [{"q": "a"}, {"q": "b"}], "response_length": "short"})
        (call,) = _tool_events(CodexCliParser().parse(_rollout([_function_call("c1", "run", arguments)])))

        assert "query" not in call.inputs

    def test_write_stdin_gets_no_command(self):
        events = CodexCliParser().parse_file(str(JSON_ARGUMENTS))
        (stdin,) = _by_action(events, "write_stdin")

        assert stdin.inputs == {"session_id": 4711, "chars": "y\n", "yield_time_ms": 1000, "max_output_tokens": 2000}

    def test_a_key_the_call_already_carries_is_never_overwritten(self):
        content = _rollout([_function_call("c1", "exec_command", '{"cmd": "a", "command": "b"}')])
        (call,) = _tool_events(CodexCliParser().parse(content))

        assert call.inputs == {"cmd": "a", "command": "b"}

    def test_flat_shape_json_string_arguments_are_decoded_not_dropped(self):
        content = "\n".join(
            [
                '{"session_id":"s","type":"session_meta","timestamp":"2026-09-10T12:00:00Z"}',
                '{"session_id":"s","type":"message","role":"assistant",'
                '"tool_calls":[{"id":"t1","name":"shell","arguments":"{\\"command\\": \\"make docs\\"}"}]}',
            ]
        )
        (call,) = _tool_events(CodexCliParser().parse(content))

        assert call.inputs == {"command": "make docs"}


class TestCodeModeExec:
    @pytest.mark.parametrize(
        ("script", "command"),
        [
            ('text(await tools.exec_command({cmd:"pytest -q"}));\n', "pytest -q"),
            ('text(await tools.exec_command({cmd:"pytest -q",max_output_tokens:6000}));', "pytest -q"),
            ('const r = await tools.exec_command({\n  cmd: "echo \\"hi\\" && ls"\n});\ntext(r);', 'echo "hi" && ls'),
            ("text(await tools.exec_command({cmd:'ls -la'}));", "ls -la"),
            ("text(await tools.exec_command({cmd:`echo $HOME`}));", "echo $HOME"),
        ],
    )
    def test_one_exec_command_call_with_a_plain_literal_gives_the_command(self, script: str, command: str):
        assert code_mode_inputs(script) == {"command": command}

    @pytest.mark.parametrize(
        "script",
        [
            "text(await tools.exec_command({cmd:`pytest ${target}`}));",
            'text(await tools.exec_command({cmd:"a\\x41"}));',
            'text(await tools.exec_command({cmd:cmdFor("unit")}));',
            'text(await tools.exec_command({workdir:"/w", cmd:"pytest"}));',
            'await tools.exec_command({cmd:"pytest"}); await tools.exec_command({cmd:"ruff check"});',
            'text(await tools.web__run({search_query:[{q:"pytest"}]}));',
            "text(ALL_TOOLS.map(x => x.name));",
            "pytest -q",
            "",
        ],
    )
    def test_anything_else_gives_nothing(self, script: str):
        assert code_mode_inputs(script) == {}

    def test_rollout_exec_keeps_the_script_and_carries_the_command(self):
        events = CodexCliParser().parse_file(str(PYTEST_RERUN))
        failed = _by_action(events, "exec")[0]

        assert failed.inputs["input"].startswith("text(await tools.exec_command(")
        assert failed.inputs["command"] == "pytest -q tests/test_parser.py"
        assert call_target(failed) == (RECOVERED_SAME_COMMAND, "pytest -q tests/test_parser.py")

    def test_code_mode_apply_patch_carries_the_file_it_touches(self):
        events = CodexCliParser().parse_file(str(APPLY_PATCH))
        (script,) = _by_action(events, "exec")

        assert script.inputs["file_path"] == "README.md"
        assert "command" not in script.inputs

    def test_redacted_exec_input_is_unchanged(self):
        content = _rollout(
            [
                {
                    "timestamp": "2026-09-10T12:00:00Z",
                    "type": "response_item",
                    "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "exec", "input": "<redacted>"},
                }
            ]
        )
        (call,) = _tool_events(CodexCliParser().parse(content))

        assert call.inputs == {"input": "<redacted>"}


class TestApplyPatch:
    def test_one_file_patch_carries_file_path(self):
        events = CodexCliParser().parse_file(str(PYTEST_RERUN))
        (patch,) = _by_action(events, "apply_patch")

        assert patch.inputs["file_path"] == "src/parser.py"
        assert patch.inputs["file_paths"] == ["src/parser.py"]
        assert patch.tool_activity["category"] == "file_io"
        assert call_target(patch) == (RECOVERED_SAME_TARGET, "src/parser.py")

    def test_multi_file_patch_lists_the_files_without_a_single_target(self):
        events = CodexCliParser().parse_file(str(APPLY_PATCH))
        multi = _by_action(events, "apply_patch")[0]

        assert multi.inputs["file_paths"] == ["docs/flags.md", "src/cli.py"]
        assert "file_path" not in multi.inputs

    def test_rename_lists_both_paths(self):
        events = CodexCliParser().parse_file(str(APPLY_PATCH))
        rename = _by_action(events, "apply_patch")[1]

        assert rename.inputs["file_paths"] == ["src/helpers.py", "src/steps.py"]

    def test_patch_in_a_json_string_argument_carries_file_path(self):
        events = CodexCliParser().parse_file(str(APPLY_PATCH))
        older = _by_action(events, "apply_patch")[2]

        assert older.inputs["file_path"] == "tests/test_flags.py"
        assert older.inputs["input"].startswith("*** Begin Patch")

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "*** Update File: src/app.py",
            "*** Begin Patch",
            "*** Begin Patch\n*** Update File: ${path}\n*** End Patch",
        ],
    )
    def test_no_plain_patch_headers_give_no_paths(self, text: str):
        assert patch_file_paths(text) == []


class TestRecoveryOnCodex:
    def test_failed_pytest_then_the_same_pytest_passing_is_recovered(self):
        run = analyse_run(PYTEST_RERUN.read_bytes(), source=PYTEST_RERUN.name)
        failed, patch, rerun = _tool_events(run.events)

        assert run.detected_format == "codex_cli"
        assert failed.tool_activity["status"] == "error"
        assert failed.failure_context["exit_code"] == 1
        assert rerun.tool_activity["status"] == "completed"
        assert failed.tool_activity["recovered_by"] == str(rerun.id)
        assert failed.tool_activity["recovery_reason"] == RECOVERED_SAME_COMMAND
        assert unrecovered_tool_failure(run.events) is False
        assert run.qualification_state == "unclassified"

    def test_the_command_ties_the_rerun_even_though_the_scripts_differ(self):
        events = CodexCliParser().parse_file(str(PYTEST_RERUN))
        failed, _, rerun = _tool_events(events)

        assert failed.inputs["input"] != rerun.inputs["input"]
        assert call_target(failed) == call_target(rerun)

    def test_failed_exec_then_an_unrelated_exec_stays_unrecovered(self):
        content = _rollout(
            [
                _exec("c1", "pytest -q tests/test_parser.py", 0),
                _exec_output("c1", "1 failed in 0.4s", 1, 0),
                _exec("c2", "ls src", 1),
                _exec_output("c2", "parser.py", 0, 1),
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
