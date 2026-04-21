"""Parser for bounded CrewAI exported run JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType


class CrewAIParser:
    """Parse a representative CrewAI run export into canonical events."""

    @property
    def source_type(self) -> str:
        return "crewai"

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        return self.parse(Path(file_path).read_text())

    def parse(self, content: str) -> list[CanonicalEvent]:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return []

        session_id = str(payload.get("run_id") or payload.get("id") or "unknown")
        started_at = self._parse_timestamp(payload.get("started_at"))
        events: list[CanonicalEvent] = []
        previous_event_id: UUID | None = None

        prompt = str(payload.get("input") or payload.get("goal") or "").strip()
        if prompt:
            user_event = CanonicalEvent(
                id=uuid4(),
                session_id=session_id,
                timestamp=started_at,
                event_type=EventType.OUTPUT,
                agent_id="user",
                action="user_message",
                parent_event_id=previous_event_id,
                inputs={},
                outputs={"text": prompt},
                metadata={
                    "source_type": self.source_type,
                    "semantic_action_category": "user_input",
                    "raw_action": "user_message",
                },
            )
            events.append(user_event)
            previous_event_id = user_event.id

        for task in payload.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            tool_calls = [tool for tool in task.get("tool_calls") or [] if isinstance(tool, dict)]
            if tool_calls:
                for index, tool_call in enumerate(tool_calls):
                    tool_event = self._build_task_event(
                        session_id=session_id,
                        task=task,
                        tool_call=tool_call,
                        tool_call_index=index,
                        parent_event_id=previous_event_id,
                    )
                    events.append(tool_event)
                    previous_event_id = tool_event.id

            final_output = str(task.get("output") or "").strip()
            if final_output:
                output_event = CanonicalEvent(
                    id=uuid4(),
                    session_id=session_id,
                    timestamp=self._parse_timestamp(task.get("completed_at") or task.get("started_at")),
                    event_type=EventType.OUTPUT,
                    agent_id=str((task.get("agent") or {}).get("role") or payload.get("crew_name") or "crewai"),
                    action="assistant_narrative",
                    parent_event_id=previous_event_id,
                    inputs={},
                    outputs={"text": final_output},
                    metadata={
                        "source_type": self.source_type,
                        "task_id": task.get("id"),
                        "semantic_action_category": "reasoning",
                        "raw_action": "task_output",
                    },
                )
                events.append(output_event)
                previous_event_id = output_event.id

        return events

    def _build_task_event(
        self,
        *,
        session_id: str,
        task: dict,
        tool_call: dict | None,
        tool_call_index: int | None,
        parent_event_id: UUID | None,
    ) -> CanonicalEvent:
        agent = task.get("agent") or {}
        action = str(
            (tool_call or {}).get("tool_name")
            or task.get("name")
            or task.get("description")
            or "task"
        )
        outputs: dict[str, object] = {}
        if tool_call is not None:
            outputs["result"] = tool_call.get("output")
            if tool_call.get("error"):
                outputs["error"] = tool_call.get("error")

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(task.get("started_at")),
            event_type=EventType.TOOL_CALL,
            agent_id=str(agent.get("role") or "crewai"),
            action=action,
            parent_event_id=parent_event_id,
            inputs={
                "description": task.get("description"),
                "expected_output": task.get("expected_output"),
                "tool_input": (tool_call or {}).get("input"),
            },
            outputs=outputs,
            metadata={
                "source_type": self.source_type,
                "task_id": task.get("id"),
                "task_status": task.get("status"),
                "agent_goal": agent.get("goal"),
                "tool_name": (tool_call or {}).get("tool_name"),
                "tool_call_index": tool_call_index,
                "semantic_action_category": "other",
                "raw_action": action,
            },
        )

    def _parse_timestamp(self, value: object) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        return datetime.now(timezone.utc)
