"""Parser for OpenClaw JSONL session transcripts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType
from driftshield.core.normalization import normalize_events


class OpenClawParser:
    """Parse OpenClaw session transcripts into canonical events."""

    HANDOFF_TOOLS = {"sessions_spawn", "subagents"}

    TOOL_CATEGORY_MAP = {
        "read": "file_io",
        "write": "file_io",
        "edit": "file_io",
        "exec": "shell",
        "browser": "browser",
        "message": "messaging",
        "sessions_spawn": "handoff",
        "subagents": "handoff",
        "web_search": "network",
        "web_fetch": "network",
        "memory_search": "memory",
        "memory_get": "memory",
    }

    @property
    def source_type(self) -> str:
        return "openclaw"

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        return normalize_events(
            self.parse(Path(file_path).read_text()),
            source_type=self.source_type,
            source_path=file_path,
        )

    def parse(self, content: str) -> list[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        session_id = "unknown"
        id_map: dict[str, UUID] = {}
        tool_call_map: dict[str, CanonicalEvent] = {}
        previous_event_id: UUID | None = None

        for raw_line in content.strip().splitlines():
            if not raw_line.strip():
                continue

            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            if entry_type == "session":
                session_id = str(entry.get("id", session_id))
                continue

            entry_id = entry.get("id")
            parent_id = id_map.get(entry.get("parentId")) or previous_event_id

            if entry_type == "message":
                message = entry.get("message") or {}
                role = message.get("role")
                content_items = message.get("content") or []

                if role == "assistant":
                    for item in content_items:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get("type")
                        if item_type == "toolCall":
                            event = self._create_tool_call_event(item, entry, session_id, parent_id)
                            events.append(event)
                            tool_call_id = item.get("id")
                            if tool_call_id:
                                tool_call_map[str(tool_call_id)] = event
                            parent_id = event.id
                            previous_event_id = event.id
                        elif item_type == "text" and item.get("text"):
                            event = self._create_text_event(
                                text=str(item.get("text", "")),
                                entry=entry,
                                session_id=session_id,
                                parent_id=parent_id,
                                agent_id="assistant",
                                action="assistant_narrative",
                                semantic_category="reply",
                            )
                            events.append(event)
                            parent_id = event.id
                            previous_event_id = event.id
                elif role == "user":
                    user_text = self._content_to_text(content_items)
                    if user_text:
                        event = self._create_text_event(
                            text=user_text,
                            entry=entry,
                            session_id=session_id,
                            parent_id=parent_id,
                            agent_id="user",
                            action="user_message",
                            semantic_category="user_input",
                        )
                        events.append(event)
                        previous_event_id = event.id
                elif role == "toolResult":
                    tool_call_id = str(message.get("toolCallId", ""))
                    tool_call_event = tool_call_map.get(tool_call_id)
                    if tool_call_event is not None:
                        tool_call_event.outputs = {
                            "result": self._content_to_text(message.get("content") or []),
                            "details": message.get("details") or {},
                            "is_error": bool(message.get("isError", False)),
                        }

            if entry_type == "custom" and entry.get("customType") == "model-snapshot":
                event = CanonicalEvent(
                    id=uuid4(),
                    session_id=session_id,
                    timestamp=self._parse_timestamp(entry.get("timestamp")),
                    event_type=EventType.BRANCH,
                    agent_id="system",
                    action="model_snapshot",
                    parent_event_id=parent_id,
                    inputs={},
                    outputs=entry.get("data") or {},
                    metadata={
                        "semantic_action_category": "model",
                        "raw_action": "model_snapshot",
                    },
                )
                events.append(event)
                previous_event_id = event.id
                if entry_id:
                    id_map[str(entry_id)] = event.id
                continue

            if entry_id and previous_event_id is not None:
                id_map[str(entry_id)] = previous_event_id

        return normalize_events(events, source_type=self.source_type)

    def _create_tool_call_event(
        self,
        item: dict,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
    ) -> CanonicalEvent:
        action = str(item.get("name", "unknown"))
        action_key = action.lower()
        event_type = EventType.HANDOFF if action_key in self.HANDOFF_TOOLS else EventType.TOOL_CALL
        arguments = item.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(entry.get("timestamp")),
            event_type=event_type,
            agent_id="assistant",
            action=action,
            parent_event_id=parent_id,
            inputs=arguments if isinstance(arguments, dict) else {"raw": arguments},
            outputs={},
            metadata={
                "tool_call_id": item.get("id"),
                "semantic_action_category": self.TOOL_CATEGORY_MAP.get(action_key, "other"),
                "raw_action": action,
            },
        )

    def _create_text_event(
        self,
        *,
        text: str,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
        agent_id: str,
        action: str,
        semantic_category: str,
    ) -> CanonicalEvent:
        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(entry.get("timestamp")),
            event_type=EventType.OUTPUT,
            agent_id=agent_id,
            action=action,
            parent_event_id=parent_id,
            inputs={},
            outputs={"text": text.strip()},
            metadata={
                "semantic_action_category": semantic_category,
                "raw_action": action,
            },
        )

    def _content_to_text(self, content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""

        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(part.strip() for part in parts if part.strip())

    def _parse_timestamp(self, value: str | int | float | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
