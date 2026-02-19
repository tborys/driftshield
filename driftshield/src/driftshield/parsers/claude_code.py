"""Parser for Claude Code JSONL transcripts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType


class ClaudeCodeParser:
    """
    Parse Claude Code session transcripts (JSONL format).

    Claude Code stores sessions as JSONL files with entries:
    - type: "assistant" with tool_use in message.content
    - type: "user" with tool_result in message.content

    Each tool_use becomes a TOOL_CALL event.
    """

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

            # Extract session ID from first entry that has it
            if session_id is None and "sessionId" in entry:
                session_id = entry["sessionId"]

            # Process assistant messages with tool_use
            if entry.get("type") == "assistant" and "message" in entry:
                message = entry["message"]
                content_items = message.get("content", [])

                for item in content_items:
                    if item.get("type") == "tool_use":
                        event = self._create_tool_call_event(
                            item=item,
                            entry=entry,
                            session_id=session_id or "unknown",
                            parent_id=prev_event_id,
                        )
                        events.append(event)
                        uuid_map[item["id"]] = event.id
                        prev_event_id = event.id

            # Process tool results to capture outputs
            if entry.get("type") == "user" and "message" in entry:
                message = entry["message"]
                content_items = message.get("content", [])

                # content can be a string (plain text) or list (tool results)
                if not isinstance(content_items, list):
                    continue

                for item in content_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "tool_result":
                        tool_use_id = item.get("tool_use_id")
                        if tool_use_id and tool_use_id in uuid_map:
                            # Find the corresponding event and update outputs
                            event_id = uuid_map[tool_use_id]
                            for e in events:
                                if e.id == event_id:
                                    e.outputs = {
                                        "result": item.get("content", ""),
                                        "is_error": item.get("is_error", False),
                                    }
                                    break

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

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=EventType.TOOL_CALL,
            agent_id=entry.get("message", {}).get("model", "claude"),
            action=item.get("name", "unknown"),
            parent_event_id=parent_id,
            inputs=item.get("input", {}),
            outputs={},  # Will be filled when we see tool_result
            metadata={
                "tool_use_id": item.get("id"),
                "cwd": entry.get("cwd"),
                "git_branch": entry.get("gitBranch"),
            },
        )

    def _parse_timestamp(self, ts: str | int | None) -> datetime:
        """Parse timestamp from ISO string or milliseconds."""
        if ts is None:
            return datetime.now(timezone.utc)

        if isinstance(ts, (int, float)):
            # Milliseconds since epoch
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

        if isinstance(ts, str):
            # ISO format: "2026-02-10T10:40:43.114Z"
            # Remove Z and parse
            ts_clean = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts_clean)

        return datetime.now(timezone.utc)
