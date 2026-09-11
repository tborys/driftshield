"""Parser for Codex CLI session transcripts.

Two on-disk shapes are supported:

* the rollout envelope Codex writes under ``~/.codex/sessions/<y>/<m>/<d>/``
  (also written by the Codex app and its VS Code extension): one
  ``{"timestamp", "type", "payload"}`` record per line, where ``type`` is
  ``session_meta``, ``turn_context``, ``event_msg``, ``response_item``,
  ``realtime_item`` or ``world_state``;
* the older flat shape with one ``message`` object per line (role, content,
  tool_calls), handled by :class:`LocalChatTranscriptParser`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType
from driftshield.parsers.local_chat import LocalChatTranscriptParser

ROLLOUT_RECORD_TYPES = frozenset(
    {"session_meta", "turn_context", "event_msg", "response_item", "realtime_item", "world_state"}
)

_TOOL_CALL_TYPES = frozenset({"custom_tool_call", "function_call"})
_TOOL_OUTPUT_TYPES = frozenset({"custom_tool_call_output", "function_call_output"})
_HANDOFF_TOOLS = frozenset({"spawn_agent", "send_message"})

# Injected context blocks arrive as user-role parts wrapped in a single tag
# (``<environment_context>...``). They are not something the user typed.
_CONTEXT_BLOCK_PATTERN = re.compile(r"^\s*<([a-z_]+)>.*</\1>\s*$", re.DOTALL)

# A rollout carries a command's exit code inside the output text, not as a
# structured flag. Two shapes: a plain ``exit=N`` line after a ``---K---``
# chunk marker, or a JSON object carrying ``"exit_code": N``. Only one of
# these clearly parsed integers counts as an exit code; words such as
# "error" in the text never do.
_EXIT_LINE_PATTERN = re.compile(r"^exit=(-?\d+)\s*$", re.MULTILINE)
_EXIT_CODE_JSON_PATTERN = re.compile(r'"exit_code"\s*:\s*(-?\d+)\b')

# How much of the output to keep next to a non zero exit code.
_OUTPUT_TAIL_CHARS = 400

# Structured input keys. The recovery matcher and the tool class checks read
# ``command`` / ``cmd``, a file path key and ``pattern`` / ``query`` / ``url``,
# the keys the transcript parsers for other agents already produce. A rollout
# states the same facts in other shapes, so the helpers below fill those keys
# from what a call clearly says and abstain on anything else.
_PATCH_BEGIN = "*** Begin Patch"
# ``*** Add File: p``, ``*** Update File: p``, ``*** Delete File: p`` and the
# ``*** Move to: p`` line of a rename, in patch order.
_PATCH_PATH_PATTERN = re.compile(
    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+?)\s*$", re.MULTILINE
)
# A code mode ``exec`` input is a script that calls tools as ``tools.name(...)``
# or ``tools["name"](...)``.
_CODE_MODE_TOOL_CALL = re.compile(
    r"\btools\s*(?:\.\s*([A-Za-z_$][\w$]*)|\[\s*([\"'])([^\"'\n]+)\2\s*\])\s*\("
)
# ``tools.exec_command({cmd: <literal>, ...})`` with ``cmd`` as the first
# property and a plain literal value: a double quoted string, a single quoted
# string without escapes, or a template literal without escapes or
# ``${...}`` interpolation.
_CODE_MODE_EXEC_COMMAND = re.compile(
    r"\btools\s*\.\s*exec_command\s*\(\s*\{\s*(?:cmd|\"cmd\"|'cmd')\s*:\s*"
    r"(\"(?:[^\"\\\n]|\\.)*\"|'[^'\\\n]*'|`(?:[^`\\$]|\$(?!\{))*`)"
)


def parse_exit_code(text: str) -> int | None:
    """The exit code a Codex tool output reports, or ``None`` when it has none.

    The last ``exit=N`` line wins, then the last ``"exit_code": N`` field.
    """
    for pattern in (_EXIT_LINE_PATTERN, _EXIT_CODE_JSON_PATTERN):
        matches = pattern.findall(text)
        if matches:
            return int(matches[-1])
    return None


def patch_file_paths(patch: str) -> list[str]:
    """The files an ``apply_patch`` body touches, in patch order.

    Empty when the text is not a patch or any header path is not plain text
    (a ``${...}`` placeholder from a script template, say).
    """
    if _PATCH_BEGIN not in patch:
        return []
    paths: list[str] = []
    for path in _PATCH_PATH_PATTERN.findall(patch):
        if not path.strip() or "${" in path:
            return []
        if path not in paths:
            paths.append(path)
    return paths


def _patch_inputs(patch: str) -> dict[str, Any]:
    paths = patch_file_paths(patch)
    if not paths:
        return {}
    filled: dict[str, Any] = {"file_paths": paths}
    # One target only when the patch touches exactly one file. A multi file
    # patch has no single target to compare, so recovery abstains on it.
    if len(paths) == 1:
        filled["file_path"] = paths[0]
    return filled


def _code_mode_exec_command(script: str) -> str | None:
    match = _CODE_MODE_EXEC_COMMAND.search(script)
    if match is None:
        return None
    literal = match.group(1)
    if literal.startswith('"'):
        try:
            value = json.loads(literal)
        except json.JSONDecodeError:
            # A JavaScript escape JSON does not know (``\'``, ``\x41``).
            return None
    else:
        value = literal[1:-1]
    return value if isinstance(value, str) and value.strip() else None


def code_mode_inputs(script: str) -> dict[str, Any]:
    """Structured inputs for a code mode ``exec`` script, or ``{}``.

    Only a script that makes exactly one tool call is read: an
    ``exec_command`` call with a plain literal ``cmd`` gives ``command``, an
    ``apply_patch`` call gives the files its patch touches. Any other script,
    including one that runs several tools, stays without structured inputs.
    """
    calls = list(_CODE_MODE_TOOL_CALL.finditer(script))
    if len(calls) != 1:
        return {}
    name = calls[0].group(1) or calls[0].group(3)
    if name == "exec_command":
        command = _code_mode_exec_command(script)
        return {"command": command} if command is not None else {}
    if name == "apply_patch":
        return _patch_inputs(script)
    return {}


def is_rollout_record(entry: Any) -> bool:
    """True for a Codex rollout envelope record."""
    return (
        isinstance(entry, dict)
        and entry.get("type") in ROLLOUT_RECORD_TYPES
        and isinstance(entry.get("payload"), dict)
    )


class CodexCliParser(LocalChatTranscriptParser):
    TOOL_CATEGORY_MAP = {
        **LocalChatTranscriptParser.TOOL_CATEGORY_MAP,
        "exec": "shell",
        "exec_command": "shell",
        "run": "shell",
        "write_stdin": "shell",
        "apply_patch": "file_io",
        "read_file": "file_io",
        "write_file": "file_io",
        "edit_file": "file_io",
        "grep": "search",
        "glob": "search",
        "ls": "search",
        "list_dir": "search",
        "git": "version_control",
        "web_search": "network",
        "fetch": "network",
        "spawn_agent": "handoff",
        "send_message": "handoff",
        "wait_agent": "handoff",
        "list_agents": "handoff",
    }

    def __init__(self) -> None:
        super().__init__(source_type="codex_cli", default_agent_id="codex_cli")

    def _parse_jsonl(self, content: str) -> list[CanonicalEvent]:
        entries: list[dict[str, Any]] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        if any(is_rollout_record(entry) for entry in entries):
            return self._parse_rollout(entries)
        return super()._parse_jsonl(content)

    # ------------------------------------------------------------------ #
    # Rollout envelope
    # ------------------------------------------------------------------ #

    def _parse_rollout(self, entries: list[dict[str, Any]]) -> list[CanonicalEvent]:
        session_id = "unknown"
        cwd: str | None = None
        model: str | None = None
        events: list[CanonicalEvent] = []
        prev_event_id: UUID | None = None
        call_event_ids: dict[str, UUID] = {}

        for index, entry in enumerate(entries):
            if not is_rollout_record(entry):
                continue
            record_type = entry["type"]
            payload = entry["payload"]
            timestamp = self._parse_timestamp(entry.get("timestamp"))

            if record_type == "session_meta":
                session_id = str(payload.get("id") or payload.get("session_id") or session_id)
                cwd = payload.get("cwd") or cwd
                continue

            if record_type == "turn_context":
                cwd = payload.get("cwd") or cwd
                model = payload.get("model") or model
                continue

            new_events: list[CanonicalEvent] = []
            if record_type == "event_msg":
                new_events = self._turn_boundary_events(
                    payload, session_id=session_id, timestamp=timestamp, parent_id=prev_event_id
                )
            elif record_type == "response_item":
                new_events = self._response_item_events(
                    payload,
                    session_id=session_id,
                    timestamp=timestamp,
                    parent_id=prev_event_id,
                    index=index,
                    cwd=cwd,
                    model=model,
                    events=events,
                    call_event_ids=call_event_ids,
                )

            for event in new_events:
                events.append(event)
                prev_event_id = event.id

        return events

    def _turn_boundary_events(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
    ) -> list[CanonicalEvent]:
        action = {"task_started": "turn_started", "task_complete": "turn_completed"}.get(
            str(payload.get("type"))
        )
        if action is None:
            return []
        return [
            CanonicalEvent(
                id=uuid4(),
                session_id=session_id,
                timestamp=timestamp,
                event_type=EventType.BRANCH,
                agent_id="system",
                action=action,
                parent_event_id=parent_id,
                inputs={},
                outputs={},
                metadata={
                    "turn_id": payload.get("turn_id"),
                    "semantic_action_category": "turn",
                    "raw_action": payload.get("type"),
                },
            )
        ]

    def _response_item_events(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        index: int,
        cwd: str | None,
        model: str | None,
        events: list[CanonicalEvent],
        call_event_ids: dict[str, UUID],
    ) -> list[CanonicalEvent]:
        item_type = payload.get("type")
        agent_id = model or self._default_agent_id

        if item_type == "message":
            return self._message_events(
                payload,
                session_id=session_id,
                timestamp=timestamp,
                parent_id=parent_id,
                index=index,
                agent_id=agent_id,
            )

        if item_type == "reasoning":
            text = self._summary_text(payload.get("summary"))
            if not text:
                return []
            return [
                self._narrative_event(
                    text,
                    session_id=session_id,
                    timestamp=timestamp,
                    parent_id=parent_id,
                    index=index,
                    agent_id=agent_id,
                    raw_action="reasoning_summary",
                )
            ]

        if item_type in _TOOL_CALL_TYPES:
            action = str(payload.get("name") or "tool_call")
            call_id = payload.get("call_id")
            category = self.TOOL_CATEGORY_MAP.get(action.lower(), "other")
            event = CanonicalEvent(
                id=uuid4(),
                session_id=session_id,
                timestamp=timestamp,
                event_type=EventType.HANDOFF if action.lower() in _HANDOFF_TOOLS else EventType.TOOL_CALL,
                agent_id=agent_id,
                action=action,
                parent_event_id=parent_id,
                inputs=self._structured_inputs(action, category, self._tool_inputs(payload)),
                outputs={},
                metadata={
                    "source_message_index": index,
                    "tool_use_id": call_id,
                    "cwd": cwd,
                    "semantic_action_category": category,
                    "raw_action": action,
                },
            )
            if call_id:
                call_event_ids[str(call_id)] = event.id
            return [event]

        if item_type in _TOOL_OUTPUT_TYPES:
            call_id = payload.get("call_id")
            event_id = call_event_ids.get(str(call_id)) if call_id else None
            if event_id is not None:
                result = self._output_text(payload.get("output"))
                for event in events:
                    if event.id == event_id:
                        event.outputs = self._tool_result_outputs(result)
                        break
            return []

        return []

    def _message_events(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        index: int,
        agent_id: str,
    ) -> list[CanonicalEvent]:
        role = str(payload.get("role") or "assistant").lower()
        if role not in {"user", "assistant"}:
            return []
        new_events: list[CanonicalEvent] = []
        for text in self._extract_texts(payload):
            if role == "user" and _CONTEXT_BLOCK_PATTERN.match(text):
                continue
            if role == "user":
                event = CanonicalEvent(
                    id=uuid4(),
                    session_id=session_id,
                    timestamp=timestamp,
                    event_type=EventType.OUTPUT,
                    agent_id="user",
                    action="user_message",
                    parent_event_id=parent_id,
                    inputs={},
                    outputs={"text": text},
                    metadata={
                        "source_message_index": index,
                        "semantic_action_category": "user_input",
                        "raw_action": "user_text",
                    },
                )
            else:
                event = self._narrative_event(
                    text,
                    session_id=session_id,
                    timestamp=timestamp,
                    parent_id=parent_id,
                    index=index,
                    agent_id=agent_id,
                    raw_action="assistant_text",
                )
            new_events.append(event)
            parent_id = event.id
        return new_events

    def _narrative_event(
        self,
        text: str,
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        index: int,
        agent_id: str,
        raw_action: str,
    ) -> CanonicalEvent:
        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=EventType.OUTPUT,
            agent_id=agent_id,
            action="assistant_narrative",
            parent_event_id=parent_id,
            inputs={},
            outputs={"text": text},
            metadata={
                "source_message_index": index,
                "semantic_action_category": "reasoning",
                "raw_action": raw_action,
            },
        )

    def _extract_texts(self, message: dict[str, Any]) -> list[str]:
        content = message.get("content")
        if not isinstance(content, list):
            return super()._extract_texts(message)
        texts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                texts.append(item.strip())
            elif (
                isinstance(item, dict)
                and item.get("type") in {"text", "input_text", "output_text"}
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ):
                texts.append(item["text"].strip())
        return texts

    def _summary_text(self, summary: object) -> str:
        if not isinstance(summary, list):
            return ""
        parts = [
            str(item["text"]).strip()
            for item in summary
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
        ]
        return "\n".join(parts)

    def _tool_inputs(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = payload.get("arguments")
        if isinstance(arguments, str):
            try:
                decoded = json.loads(arguments)
            except json.JSONDecodeError:
                return {"arguments": arguments}
            return decoded if isinstance(decoded, dict) else {"arguments": decoded}
        if isinstance(arguments, dict):
            return arguments
        raw_input = payload.get("input")
        if isinstance(raw_input, dict):
            return raw_input
        if isinstance(raw_input, str):
            return {"input": raw_input}
        return {}

    def _structured_inputs(
        self, action: str, category: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """``inputs`` plus the structured keys a call's own inputs clearly state.

        Adds ``command`` for a shell call (from ``cmd``, or from a code mode
        ``exec`` script), ``file_path`` / ``file_paths`` for ``apply_patch``
        and the file tools, and ``query`` for a ``run`` web search with one
        query. A key the call already carries is never overwritten.
        ``write_stdin`` sends keystrokes to a running session, not a command,
        so it gets none.
        """
        name = action.lower()
        filled: dict[str, Any] = {}
        raw_text = inputs.get("input") if len(inputs) == 1 else None

        if name == "apply_patch":
            patch = next(
                (inputs[key] for key in ("input", "patch") if isinstance(inputs.get(key), str)),
                "",
            )
            filled = _patch_inputs(patch)
        elif name == "write_stdin":
            filled = {}
        elif category == "shell":
            if isinstance(inputs.get("cmd"), str):
                filled["command"] = inputs["cmd"]
            elif isinstance(raw_text, str):
                filled = code_mode_inputs(raw_text)
            queries = inputs.get("search_query")
            if (
                name == "run"
                and isinstance(queries, list)
                and len(queries) == 1
                and isinstance(queries[0], dict)
                and isinstance(queries[0].get("q"), str)
            ):
                filled["query"] = queries[0]["q"]
        elif category == "file_io" and isinstance(inputs.get("path"), str):
            filled["file_path"] = inputs["path"]

        return {**inputs, **{key: value for key, value in filled.items() if key not in inputs}}

    def _coerce_dict(self, value: object) -> dict:
        """Flat shape tool arguments. A JSON object string is decoded, not dropped."""
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return decoded if isinstance(decoded, dict) else {}
        return super()._coerce_dict(value)

    def _tool_result_outputs(self, result: str) -> dict[str, Any]:
        """Outputs for a tool result, flagging a non zero exit code as an error.

        ``is_error`` and ``error`` are the same keys the other parsers use, so
        normalisation turns them into ``failure_context`` and
        ``tool_activity.status == "error"`` without a Codex specific branch.
        """
        outputs: dict[str, Any] = {"result": result}
        exit_code = parse_exit_code(result)
        if exit_code is None:
            return outputs
        outputs["exit_code"] = exit_code
        if exit_code != 0:
            outputs["is_error"] = True
            outputs["error"] = result[-_OUTPUT_TAIL_CHARS:].strip()
        return outputs

    def _output_text(self, output: object) -> str:
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            chunks = [
                str(item["text"])
                for item in output
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ] + [item for item in output if isinstance(item, str)]
            return "\n".join(chunk for chunk in chunks if chunk)
        if output is None:
            return ""
        return json.dumps(output)
