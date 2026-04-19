"""Parser for LangSmith / LangChain exported run JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType


class LangChainParser:
    """Parse bounded LangSmith / LangChain exported run JSON into canonical events."""

    def __init__(self) -> None:
        self._default_agent_id = "langchain"

    @property
    def source_type(self) -> str:
        return "langchain"

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        return self.parse(Path(file_path).read_text())

    def parse(self, content: str) -> list[CanonicalEvent]:
        payload = json.loads(content)
        runs = self._normalise_runs(payload)
        if not runs:
            return []

        root_run = self._select_root_run(runs)
        session_id = str(root_run.get("trace_id") or root_run.get("id") or "unknown")
        scoped_runs = self._runs_for_root(runs, root_run)
        ordered_runs = sorted(scoped_runs, key=self._run_sort_key)

        events: list[CanonicalEvent] = []
        previous_event_id: UUID | None = None

        for message in self._extract_messages(root_run.get("inputs"), role="user"):
            event = self._build_output_event(
                session_id=session_id,
                timestamp=self._parse_timestamp(root_run.get("start_time")),
                parent_event_id=previous_event_id,
                agent_id="user",
                action="user_message",
                text=message,
                metadata={
                    "source_type": self.source_type,
                    "root_run_id": root_run.get("id"),
                    "semantic_action_category": "user_input",
                    "raw_action": "user_message",
                },
            )
            events.append(event)
            previous_event_id = event.id

        for run in ordered_runs:
            if str(run.get("run_type", "")).lower() != "tool":
                continue
            event = self._build_tool_event(
                run=run,
                session_id=session_id,
                parent_event_id=previous_event_id,
            )
            events.append(event)
            previous_event_id = event.id

        for message in self._extract_messages(root_run.get("outputs"), role="assistant"):
            event = self._build_output_event(
                session_id=session_id,
                timestamp=self._parse_timestamp(root_run.get("end_time") or root_run.get("start_time")),
                parent_event_id=previous_event_id,
                agent_id=self._default_agent_id,
                action="assistant_narrative",
                text=message,
                metadata={
                    "source_type": self.source_type,
                    "root_run_id": root_run.get("id"),
                    "semantic_action_category": "reasoning",
                    "raw_action": "assistant_narrative",
                },
            )
            events.append(event)
            previous_event_id = event.id

        return events

    def _normalise_runs(self, payload: dict | list) -> list[dict]:
        if isinstance(payload, list):
            runs = [run for run in payload if isinstance(run, dict)]
            nested_runs: list[dict] = []
            for run in runs:
                nested_runs.extend(self._flatten_child_runs(run))
            return self._deduplicate_runs([*runs, *nested_runs])

        if not isinstance(payload, dict):
            return []

        runs = [payload]
        runs.extend(self._flatten_child_runs(payload))
        return self._deduplicate_runs(runs)

    def _flatten_child_runs(self, run: dict) -> list[dict]:
        flattened: list[dict] = []
        for child in run.get("child_runs") or []:
            if not isinstance(child, dict):
                continue
            flattened.append(child)
            flattened.extend(self._flatten_child_runs(child))
        return flattened

    def _deduplicate_runs(self, runs: list[dict]) -> list[dict]:
        deduped: dict[str, dict] = {}
        anonymous: list[dict] = []
        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                anonymous.append(run)
                continue
            deduped[str(run_id)] = run
        return [*deduped.values(), *anonymous]

    def _select_root_run(self, runs: list[dict]) -> dict:
        roots = [run for run in runs if not run.get("parent_run_id")]
        if not roots:
            roots = runs
        return sorted(roots, key=self._run_sort_key)[0]

    def _runs_for_root(self, runs: list[dict], root_run: dict) -> list[dict]:
        root_id = root_run.get("id")
        root_trace_id = root_run.get("trace_id")
        descendant_ids = self._collect_descendant_ids(runs, root_id)

        scoped_runs: list[dict] = []
        for run in runs:
            run_id = run.get("id")
            if run is root_run:
                scoped_runs.append(run)
                continue
            if run_id is not None and str(run_id) in descendant_ids:
                scoped_runs.append(run)
                continue
            if root_id is None and root_trace_id is not None and run.get("trace_id") == root_trace_id:
                scoped_runs.append(run)
        return scoped_runs

    def _collect_descendant_ids(self, runs: list[dict], root_id: object) -> set[str]:
        if root_id is None:
            return set()

        children_by_parent: dict[str, list[str]] = {}
        for run in runs:
            run_id = run.get("id")
            parent_id = run.get("parent_run_id")
            if run_id is None or parent_id is None:
                continue
            children_by_parent.setdefault(str(parent_id), []).append(str(run_id))

        descendants: set[str] = set()
        stack = [str(root_id)]
        while stack:
            current = stack.pop()
            for child_id in children_by_parent.get(current, []):
                if child_id in descendants:
                    continue
                descendants.add(child_id)
                stack.append(child_id)
        return descendants

    def _run_sort_key(self, run: dict) -> tuple[int, tuple[tuple[int, int | str], ...], float, str]:
        execution_order = run.get("dotted_order") or run.get("execution_order")
        order_parts = self._execution_order_parts(execution_order)
        if order_parts is not None:
            return (0, order_parts, 0.0, str(run.get("id") or ""))

        timestamp = self._parse_timestamp(run.get("start_time"))
        return (1, (), timestamp.timestamp(), str(run.get("id") or ""))

    def _execution_order_parts(self, value: object) -> tuple[tuple[int, int | str], ...] | None:
        if isinstance(value, int):
            return ((0, value),)
        if isinstance(value, float):
            return ((0, int(value)),)
        if isinstance(value, str):
            pieces = [piece for piece in value.split(".") if piece]
            if not pieces:
                return None
            if all(piece.isdigit() for piece in pieces):
                return tuple((0, int(piece)) for piece in pieces)
            return tuple((1, piece) for piece in pieces)
        return None

    def _build_output_event(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        parent_event_id: UUID | None,
        agent_id: str,
        action: str,
        text: str,
        metadata: dict,
    ) -> CanonicalEvent:
        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=EventType.OUTPUT,
            agent_id=agent_id,
            action=action,
            parent_event_id=parent_event_id,
            inputs={},
            outputs={"text": text},
            metadata=metadata,
        )

    def _build_tool_event(
        self,
        *,
        run: dict,
        session_id: str,
        parent_event_id: UUID | None,
    ) -> CanonicalEvent:
        outputs = {"result": run.get("outputs")}
        if run.get("error"):
            outputs["error"] = run.get("error")

        metadata = {
            "source_type": self.source_type,
            "run_id": run.get("id"),
            "parent_run_id": run.get("parent_run_id"),
            "trace_id": run.get("trace_id"),
            "run_type": run.get("run_type"),
            "raw_action": run.get("name"),
            "semantic_action_category": "other",
        }
        if run.get("error"):
            metadata["error"] = run.get("error")

        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=self._parse_timestamp(run.get("start_time")),
            event_type=EventType.TOOL_CALL,
            agent_id=self._default_agent_id,
            action=str(run.get("name") or "tool"),
            parent_event_id=parent_event_id,
            inputs=self._coerce_dict(run.get("inputs")),
            outputs=outputs,
            metadata=metadata,
        )

    def _extract_messages(self, payload: object, *, role: str) -> list[str]:
        if not isinstance(payload, dict):
            return []

        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []

        extracted: list[str] = []
        for message in messages:
            text = self._message_text(message, role=role)
            if text:
                extracted.append(text)
        return extracted

    def _message_text(self, message: object, *, role: str) -> str:
        if not isinstance(message, dict):
            return ""

        message_role = str(message.get("role") or message.get("type") or "").lower()
        if role == "user" and message_role not in {"human", "user"}:
            return ""
        if role == "assistant" and message_role not in {"ai", "assistant"}:
            return ""

        content = message.get("content")
        return self._content_to_text(content)

    def _content_to_text(self, content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                    elif item.get("type") == "text":
                        value = item.get("value")
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
            return "\n".join(parts)
        if isinstance(content, dict):
            text = content.get("text") or content.get("value")
            if isinstance(text, str):
                return text.strip()
        return ""

    def _coerce_dict(self, value: object) -> dict:
        return value if isinstance(value, dict) else {}

    def _parse_timestamp(self, value: str | int | float | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
