"""Shared parser helpers for local desktop/CLI chat transcripts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType


class LocalChatTranscriptParser:
    TOOL_CATEGORY_MAP = {
        "read": "file_io",
        "write": "file_io",
        "edit": "file_io",
        "shell": "shell",
        "bash": "shell",
        "command": "shell",
    }

    def __init__(self, *, source_type: str, default_agent_id: str):
        self._source_type = source_type
        self._default_agent_id = default_agent_id

    @property
    def source_type(self) -> str:
        return self._source_type

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        path = Path(file_path)
        content = path.read_text()
        if path.suffix == ".jsonl":
            return self._parse_jsonl(content)
        return self._parse_json(json.loads(content))

    def parse(self, content: str) -> list[CanonicalEvent]:
        stripped = content.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return self._parse_json(json.loads(content))
        return self._parse_jsonl(content)

    def _parse_jsonl(self, content: str) -> list[CanonicalEvent]:
        messages: list[dict] = []
        session_id: str | None = None
        started_at: str | None = None
        for line in content.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            session_id = session_id or entry.get("session_id") or entry.get("sessionId") or entry.get("id")
            if entry.get("type") in {"session", "session_meta"}:
                started_at = started_at or entry.get("timestamp")
                continue
            messages.append(entry)
        payload = {
            "session_id": session_id,
            "started_at": started_at,
            "messages": messages,
        }
        return self._parse_json(payload)

    def _parse_json(self, payload: dict | list) -> list[CanonicalEvent]:
        if isinstance(payload, list):
            payload = {"messages": payload}

        session_id = str(payload.get("session_id") or payload.get("sessionId") or payload.get("id") or "unknown")
        messages = payload.get("messages") or payload.get("conversation") or payload.get("transcript") or []

        events: list[CanonicalEvent] = []
        prev_event_id: UUID | None = None
        tool_event_ids: dict[str, UUID] = {}

        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            timestamp = self._parse_timestamp(message.get("timestamp") or payload.get("started_at"))
            role = (message.get("role") or message.get("type") or "assistant").lower()

            for text in self._extract_texts(message):
                event = CanonicalEvent(
                    id=uuid4(),
                    session_id=session_id,
                    timestamp=timestamp,
                    event_type=EventType.OUTPUT,
                    agent_id="user" if role == "user" else self._default_agent_id,
                    action="user_message" if role == "user" else "assistant_narrative",
                    parent_event_id=prev_event_id,
                    inputs={},
                    outputs={"text": text},
                    metadata={
                        "source_message_index": index,
                        "semantic_action_category": "user_input" if role == "user" else "reasoning",
                        "raw_action": "text",
                    },
                )
                events.append(event)
                prev_event_id = event.id

            for tool_call in self._extract_tool_calls(message):
                action = str(tool_call.get("name") or tool_call.get("toolName") or "tool_call")
                event = CanonicalEvent(
                    id=uuid4(),
                    session_id=session_id,
                    timestamp=timestamp,
                    event_type=EventType.TOOL_CALL,
                    agent_id=self._default_agent_id,
                    action=action,
                    parent_event_id=prev_event_id,
                    inputs=self._coerce_dict(tool_call.get("arguments") or tool_call.get("input")),
                    outputs=self._tool_outputs(tool_call),
                    metadata={
                        "source_message_index": index,
                        "tool_use_id": tool_call.get("id") or tool_call.get("toolCallId"),
                        "semantic_action_category": self.TOOL_CATEGORY_MAP.get(action.lower(), "other"),
                        "raw_action": action,
                    },
                )
                events.append(event)
                prev_event_id = event.id
                tool_id = tool_call.get("id") or tool_call.get("toolCallId")
                if tool_id:
                    tool_event_ids[str(tool_id)] = event.id

            if role in {"tool", "tool_result"}:
                tool_id = message.get("toolCallId") or message.get("tool_call_id")
                if tool_id and tool_id in tool_event_ids:
                    for event in events:
                        if event.id == tool_event_ids[tool_id]:
                            event.outputs = self._tool_outputs(message)
                            break

        return events

    def _extract_texts(self, message: dict) -> list[str]:
        content = message.get("content")
        if isinstance(content, str):
            return [content.strip()] if content.strip() else []
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    texts.append(item.strip())
                elif isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    texts.append(str(item["text"]).strip())
            return [text for text in texts if text]
        return []

    def _extract_tool_calls(self, message: dict) -> list[dict]:
        tool_calls = message.get("tool_calls") or message.get("toolCalls")
        if isinstance(tool_calls, list):
            return [item for item in tool_calls if isinstance(item, dict)]
        content = message.get("content")
        if isinstance(content, list):
            return [
                item
                for item in content
                if isinstance(item, dict) and item.get("type") in {"tool_call", "tool_use", "toolCall"}
            ]
        return []

    def _tool_outputs(self, payload: dict) -> dict:
        result = payload.get("result")
        if result is None:
            result = payload.get("content")
        if isinstance(result, list):
            text_chunks = []
            for item in result:
                if isinstance(item, str):
                    text_chunks.append(item)
                elif isinstance(item, dict) and item.get("text"):
                    text_chunks.append(str(item["text"]))
            result = "\n".join(chunk for chunk in text_chunks if chunk)
        return {"result": result} if result is not None else {}

    def _coerce_dict(self, value: object) -> dict:
        return value if isinstance(value, dict) else {}

    def _parse_timestamp(self, value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
