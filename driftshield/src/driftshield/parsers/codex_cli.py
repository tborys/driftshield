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
                inputs=self._tool_inputs(payload),
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
                        event.outputs = {"result": result}
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
