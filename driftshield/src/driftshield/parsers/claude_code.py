"""Parser for Claude Code JSONL transcripts."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType


class ClaudeCodeParser:
    """
    Parse Claude Code session transcripts (JSONL format).

    Supports:
    - assistant tool_use records
    - assistant narrative text records
    - user tool_result records mapped back to tool_use outputs
    - progress hook records for timeline/provenance fidelity
    """

    HANDOFF_TOOLS = {"task", "subagent", "spawn_subagent", "delegate_task"}
    NARRATIVE_HANDOFF_PATTERN = re.compile(r"\b(handoff|subagent|delegate|spawn)\b")

    TOOL_CATEGORY_MAP = {
        "read": "file_io",
        "write": "file_io",
        "edit": "file_io",
        "bash": "shell",
        "exec": "shell",
        "grep": "search",
        "glob": "search",
        "ls": "search",
        "git": "version_control",
        "task": "handoff",
        "websearch": "network",
        "web_fetch": "network",
    }

    @property
    def source_type(self) -> str:
        return "claude_code"

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        """Parse transcript from file path."""
        content = Path(file_path).read_text()
        return self.parse(content)

    def parse(self, content: str) -> list[CanonicalEvent]:
        """Parse raw JSONL content into canonical events."""
        events: list[CanonicalEvent] = []
        session_id: str | None = None
        uuid_map: dict[str, UUID] = {}  # tool_use_id -> our UUID
        prev_event_id: UUID | None = None

        for line in content.strip().split("\n"):
            if not line.strip():
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if session_id is None and "sessionId" in entry:
                session_id = entry["sessionId"]

            if entry.get("type") == "assistant" and "message" in entry:
                message = entry["message"]
                content_items = message.get("content", [])

                for item in content_items:
                    if not isinstance(item, dict):
                        continue

                    if item.get("type") == "tool_use":
                        event = self._create_tool_call_event(
                            item=item,
                            entry=entry,
                            session_id=session_id or "unknown",
                            parent_id=prev_event_id,
                        )
                        events.append(event)
                        tool_use_id = item.get("id")
                        if tool_use_id:
                            uuid_map[tool_use_id] = event.id
                        prev_event_id = event.id

                    if item.get("type") == "text" and item.get("text"):
                        event = self._create_narrative_event(
                            item=item,
                            entry=entry,
                            session_id=session_id or "unknown",
                            parent_id=prev_event_id,
                        )
                        events.append(event)
                        prev_event_id = event.id

            if entry.get("type") == "progress":
                progress_event = self._create_progress_event(
                    entry=entry,
                    session_id=session_id or "unknown",
                    parent_id=prev_event_id,
                )
                if progress_event is not None:
                    events.append(progress_event)
                    prev_event_id = progress_event.id

            if entry.get("type") == "user" and "message" in entry:
                message = entry["message"]
                content_items = message.get("content", [])

                if isinstance(content_items, str):
                    text_event = self._create_user_message_event(
                        text=content_items,
                        entry=entry,
                        session_id=session_id or "unknown",
                        parent_id=prev_event_id,
                    )
                    if text_event is not None:
                        events.append(text_event)
                        prev_event_id = text_event.id
                    continue

                if not isinstance(content_items, list):
                    continue

                for item in content_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "tool_result":
                        tool_use_id = item.get("tool_use_id")
                        if tool_use_id and tool_use_id in uuid_map:
                            event_id = uuid_map[tool_use_id]
                            for e in events:
                                if e.id == event_id:
                                    e.outputs = {
                                        "result": item.get("content", ""),
                                        "is_error": item.get("is_error", False),
                                    }
                                    break
                    elif item.get("type") == "text" and item.get("text"):
                        text_event = self._create_user_message_event(
                            text=item["text"],
                            entry=entry,
                            session_id=session_id or "unknown",
                            parent_id=prev_event_id,
                        )
                        if text_event is not None:
                            events.append(text_event)
                            prev_event_id = text_event.id

        return events

    def _create_tool_call_event(
        self,
        item: dict,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
    ) -> CanonicalEvent:
        """Create a CanonicalEvent from a tool_use item."""
        timestamp = self._parse_timestamp(entry.get("timestamp"))
        raw_action = item.get("name", "unknown")
        semantic_category = self._semantic_category_for_action(raw_action)
        event_type = EventType.HANDOFF if raw_action.lower() in self.HANDOFF_TOOLS else EventType.TOOL_CALL

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
            agent_id=entry.get("message", {}).get("model", "claude"),
            action=raw_action,
            parent_event_id=parent_id,
            inputs=item.get("input", {}),
            outputs={},
            metadata={
                "tool_use_id": item.get("id"),
                "cwd": entry.get("cwd"),
                "git_branch": entry.get("gitBranch"),
                "raw_action": raw_action,
                "semantic_action_category": semantic_category,
            },
        )

    def _create_narrative_event(
        self,
        item: dict,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
    ) -> CanonicalEvent:
        text = item.get("text", "")
        event_type = (
            EventType.HANDOFF
            if self.NARRATIVE_HANDOFF_PATTERN.search(text.lower())
            else EventType.OUTPUT
        )

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(entry.get("timestamp")),
            event_type=event_type,
            agent_id=entry.get("message", {}).get("model", "claude"),
            action="assistant_handoff" if event_type == EventType.HANDOFF else "assistant_narrative",
            parent_event_id=parent_id,
            inputs={},
            outputs={"text": text},
            metadata={
                "semantic_action_category": "handoff" if event_type == EventType.HANDOFF else "reasoning",
                "raw_action": "assistant_text",
            },
        )

    def _create_user_message_event(
        self,
        text: str,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
    ) -> CanonicalEvent | None:
        cleaned = text.strip()
        if not cleaned:
            return None

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(entry.get("timestamp")),
            event_type=EventType.OUTPUT,
            agent_id="user",
            action="user_message",
            parent_event_id=parent_id,
            inputs={},
            outputs={"text": cleaned},
            metadata={
                "semantic_action_category": "user_input",
                "raw_action": "user_text",
            },
        )

    def _create_progress_event(
        self,
        entry: dict,
        session_id: str,
        parent_id: UUID | None,
    ) -> CanonicalEvent | None:
        data = entry.get("data")
        if not isinstance(data, dict):
            return None

        # Claude Code currently emits hook lifecycle events under hook_progress.
        # Ignore other progress subtypes until we define a stable canonical mapping.
        if data.get("type") != "hook_progress":
            return None

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(entry.get("timestamp")),
            event_type=EventType.BRANCH,
            agent_id=entry.get("userType", "claude"),
            action="hook_progress",
            parent_event_id=parent_id,
            inputs={},
            outputs={},
            metadata={
                "hook_event": data.get("hookEvent"),
                "hook_name": data.get("hookName"),
                "command": data.get("command"),
                "parent_tool_use_id": entry.get("parentToolUseID"),
                "tool_use_id": entry.get("toolUseID"),
                "semantic_action_category": "hook",
                "raw_action": "hook_progress",
            },
        )

    def _semantic_category_for_action(self, action: str) -> str:
        action_key = action.lower()
        return self.TOOL_CATEGORY_MAP.get(action_key, "other")

    def _parse_timestamp(self, ts: str | int | None) -> datetime:
        """Parse timestamp from ISO string or milliseconds."""
        if ts is None:
            return datetime.now(timezone.utc)

        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

        if isinstance(ts, str):
            ts_clean = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts_clean)

        return datetime.now(timezone.utc)
