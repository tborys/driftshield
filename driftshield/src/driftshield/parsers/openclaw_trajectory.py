"""Parser for OpenClaw runtime trajectory JSONL files.

OpenClaw writes two distinct JSONL formats. The session transcript
(``~/.openclaw/agents/<agent>/sessions/<id>.jsonl``) carries the full
conversation and is handled by :class:`~driftshield.parsers.openclaw.OpenClawParser`.
The runtime trajectory (``*.trajectory.jsonl``) is the telemetry the runtime
emits per run: lifecycle records (``session.started`` → ``trace.metadata`` →
``context.compiled`` → ``prompt.submitted`` → ``model.completed`` →
``trace.artifacts`` → ``session.ended``), each wrapped in a run/trace
correlation envelope (``runId`` / ``traceId`` / ``schemaVersion`` / ``seq`` /
``source``).

This parser maps the trajectory into canonical events so trajectory
submissions stop being unparseable: the prompt, the model completion (with
its abort/timeout failure signals), the per-tool-call records recovered from
``trace.artifacts.toolMetas``, and the run outcome. Failure information is
emitted through ``outputs.error`` / ``outputs.is_error`` so
:func:`driftshield.core.normalization.normalize_events` derives the
``failure_context`` the deterministic matcher keys on.

Trajectory records the parser does not recognise are skipped, so newer
runtime schema versions degrade to a thinner trace instead of failing.
``context.compiled`` is skipped deliberately: its prompt/system-prompt/tool
content duplicates ``prompt.submitted`` and the tool inventory while being
the most sensitive record in the file.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from driftshield.core.models import CanonicalEvent, EventType
from driftshield.core.normalization import normalize_events
from driftshield.parsers.openclaw import OpenClawParser


class OpenClawTrajectoryParser:
    """Parse OpenClaw runtime trajectories into canonical events."""

    # Same handoff/category semantics as the session-transcript parser, so
    # the two OpenClaw formats classify tools identically.
    HANDOFF_TOOLS = OpenClawParser.HANDOFF_TOOLS
    TOOL_CATEGORY_MAP = OpenClawParser.TOOL_CATEGORY_MAP

    @property
    def source_type(self) -> str:
        return "openclaw_trajectory"

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        return normalize_events(
            self.parse(Path(file_path).read_text()),
            source_type=self.source_type,
            source_path=file_path,
        )

    def parse(self, content: str) -> list[CanonicalEvent]:
        records = self._load_records(content)
        if not records:
            return []

        session_id = "unknown"
        for record in records:
            candidate = record.get("sessionId")
            if isinstance(candidate, str) and candidate:
                session_id = candidate
                break

        base_time = self._base_time(records)
        events: list[CanonicalEvent] = []
        previous_event_id: UUID | None = None

        for index, record in enumerate(records):
            record_type = record.get("type")
            data = record.get("data")
            data = data if isinstance(data, dict) else {}
            timestamp = self._record_time(record, base_time, index)

            new_events: list[CanonicalEvent] = []
            if record_type == "session.started":
                new_events.append(
                    self._event(
                        session_id=session_id,
                        timestamp=timestamp,
                        event_type=EventType.OUTPUT,
                        agent_id="system",
                        action="session_started",
                        parent_id=previous_event_id,
                        outputs=self._scalars(
                            data, ("trigger", "agentId", "toolCount", "messageChannel")
                        ),
                        semantic_category="session",
                    )
                )
            elif record_type == "trace.metadata":
                model = data.get("model")
                model = model if isinstance(model, dict) else {}
                snapshot = self._scalars(
                    model, ("provider", "name", "api", "thinkLevel")
                )
                for key in ("provider", "modelId", "modelApi"):
                    value = record.get(key)
                    if isinstance(value, (str, int, float, bool)):
                        snapshot.setdefault(key, value)
                new_events.append(
                    self._event(
                        session_id=session_id,
                        timestamp=timestamp,
                        event_type=EventType.BRANCH,
                        agent_id="system",
                        action="model_snapshot",
                        parent_id=previous_event_id,
                        outputs=snapshot,
                        semantic_category="model",
                    )
                )
            elif record_type == "prompt.submitted":
                prompt = data.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    new_events.append(
                        self._event(
                            session_id=session_id,
                            timestamp=timestamp,
                            event_type=EventType.OUTPUT,
                            agent_id="user",
                            action="user_message",
                            parent_id=previous_event_id,
                            outputs={"text": prompt.strip()},
                            semantic_category="user_input",
                        )
                    )
            elif record_type == "model.completed":
                new_events.append(
                    self._model_completed_event(
                        session_id=session_id,
                        timestamp=timestamp,
                        parent_id=previous_event_id,
                        data=data,
                    )
                )
            elif record_type == "trace.artifacts":
                new_events.extend(
                    self._trace_artifact_events(
                        session_id=session_id,
                        timestamp=timestamp,
                        parent_id=previous_event_id,
                        data=data,
                    )
                )
            elif record_type == "session.ended":
                new_events.append(
                    self._session_ended_event(
                        session_id=session_id,
                        timestamp=timestamp,
                        parent_id=previous_event_id,
                        data=data,
                    )
                )

            for event in new_events:
                events.append(event)
                previous_event_id = event.id

        return normalize_events(events, source_type=self.source_type)

    def _model_completed_event(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        data: dict[str, Any],
    ) -> CanonicalEvent:
        outputs: dict[str, Any] = {}
        assistant_texts = data.get("assistantTexts")
        if isinstance(assistant_texts, list):
            joined = "\n".join(
                text.strip() for text in assistant_texts if isinstance(text, str) and text.strip()
            )
            if joined:
                outputs["text"] = joined
        error = self._failure_reason(data)
        if error is not None:
            outputs["error"] = error
            outputs["is_error"] = True
        usage = data.get("usage")
        metadata_extra: dict[str, Any] = {}
        if isinstance(usage, dict) and isinstance(usage.get("total"), (int, float)):
            metadata_extra["token_total"] = usage["total"]
        return self._event(
            session_id=session_id,
            timestamp=timestamp,
            event_type=EventType.OUTPUT,
            agent_id="assistant",
            action="model_completed",
            parent_id=parent_id,
            outputs=outputs,
            semantic_category="reply",
            metadata_extra=metadata_extra,
        )

    def _trace_artifact_events(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        data: dict[str, Any],
    ) -> list[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        tool_metas = data.get("toolMetas")
        if isinstance(tool_metas, list):
            for offset, entry in enumerate(tool_metas):
                if not isinstance(entry, dict):
                    continue
                tool_name = entry.get("toolName")
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                action_key = tool_name.lower()
                event_type = (
                    EventType.HANDOFF
                    if action_key in self.HANDOFF_TOOLS
                    else EventType.TOOL_CALL
                )
                inputs: dict[str, Any] = {}
                meta = entry.get("meta")
                if isinstance(meta, str) and meta.strip():
                    inputs["meta"] = meta.strip()
                event = self._event(
                    session_id=session_id,
                    timestamp=timestamp + timedelta(microseconds=offset),
                    event_type=event_type,
                    agent_id="assistant",
                    action=tool_name,
                    parent_id=parent_id,
                    inputs=inputs,
                    outputs={},
                    semantic_category=self.TOOL_CATEGORY_MAP.get(action_key, "other"),
                )
                events.append(event)
                parent_id = event.id

        final_status = data.get("finalStatus")
        if isinstance(final_status, str) and final_status and final_status != "success":
            error = self._failure_reason(data) or f"run finished with status {final_status}"
            events.append(
                self._event(
                    session_id=session_id,
                    timestamp=timestamp + timedelta(milliseconds=1),
                    event_type=EventType.OUTPUT,
                    agent_id="system",
                    action="run_outcome",
                    parent_id=parent_id,
                    outputs={"status": final_status, "error": error, "is_error": True},
                    semantic_category="session",
                )
            )
        return events

    def _session_ended_event(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        parent_id: UUID | None,
        data: dict[str, Any],
    ) -> CanonicalEvent:
        status = data.get("status")
        outputs: dict[str, Any] = {}
        if isinstance(status, str) and status:
            outputs["status"] = status
        error = self._failure_reason(data)
        if error is None and isinstance(status, str) and status and status != "success":
            error = f"session ended with status {status}"
        if error is not None:
            outputs["error"] = error
            outputs["is_error"] = True
        return self._event(
            session_id=session_id,
            timestamp=timestamp,
            event_type=EventType.OUTPUT,
            agent_id="system",
            action="session_ended",
            parent_id=parent_id,
            outputs=outputs,
            semantic_category="session",
        )

    @staticmethod
    def _failure_reason(data: dict[str, Any]) -> str | None:
        """Map the runtime's failure flags to one explicit reason string."""
        prompt_error = data.get("promptErrorSource")
        if isinstance(prompt_error, str) and prompt_error.strip():
            return f"prompt error: {prompt_error.strip()}"
        if data.get("aborted") is True or data.get("externalAbort") is True:
            return "run aborted"
        if data.get("timedOut") is True or data.get("timedOutDuringCompaction") is True:
            return "run timed out"
        if data.get("idleTimedOut") is True:
            return "run idle timed out"
        return None

    @staticmethod
    def _scalars(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {
            key: data[key]
            for key in keys
            if isinstance(data.get(key), (str, int, float, bool))
        }

    def _event(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        event_type: EventType,
        agent_id: str,
        action: str,
        parent_id: UUID | None,
        outputs: dict[str, Any],
        semantic_category: str,
        inputs: dict[str, Any] | None = None,
        metadata_extra: dict[str, Any] | None = None,
    ) -> CanonicalEvent:
        metadata: dict[str, Any] = {
            "semantic_action_category": semantic_category,
            "raw_action": action,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        return CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
            agent_id=agent_id,
            action=action,
            parent_event_id=parent_id,
            inputs=inputs or {},
            outputs=outputs,
            metadata=metadata,
        )

    @staticmethod
    def _load_records(content: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for raw_line in content.strip().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                records.append(entry)
        return records

    def _base_time(self, records: list[dict[str, Any]]) -> datetime:
        """Earliest ``data.capturedAt`` in the file, else now.

        Trajectory records carry no per-record timestamp; ordering comes from
        ``seq``. The base anchors the synthetic per-record timestamps.
        """
        captured: list[datetime] = []
        for record in records:
            data = record.get("data")
            if not isinstance(data, dict):
                continue
            raw = data.get("capturedAt")
            if not isinstance(raw, str):
                continue
            try:
                captured.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                continue
        if captured:
            return min(captured)
        return datetime.now(timezone.utc)

    @staticmethod
    def _record_time(
        record: dict[str, Any], base_time: datetime, index: int
    ) -> datetime:
        seq = record.get("seq")
        offset = seq if isinstance(seq, int) and seq >= 0 else index
        return base_time + timedelta(milliseconds=offset)
