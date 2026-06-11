"""Tests for the OpenClaw runtime trajectory parser."""

from __future__ import annotations

import json
from typing import Any

from driftshield.core.models import EventType
from driftshield.parsers.openclaw_trajectory import OpenClawTrajectoryParser


SESSION_ID = "8ad36b0f-9181-4961-9263-770f657db9f5"


def _record(record_type: str, seq: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": record_type,
        "runId": "run-1",
        "traceId": "trace-1",
        "schemaVersion": 1,
        "seq": seq,
        "source": "runtime",
        "sessionId": SESSION_ID,
        "sessionKey": "agent:engineering:cron:run-1",
        "sourceSeq": seq,
        "provider": "openai-codex",
        "modelId": "gpt-5.4",
        "modelApi": "openai-codex-responses",
        "data": data,
    }


def _success_trajectory() -> str:
    records = [
        _record(
            "session.started",
            0,
            {"agentId": "engineering", "trigger": "cron", "toolCount": 20},
        ),
        _record(
            "trace.metadata",
            1,
            {
                "capturedAt": "2026-05-01T03:00:00.000Z",
                "model": {
                    "api": "openai-codex-responses",
                    "name": "gpt-5.4",
                    "provider": "openai-codex",
                    "thinkLevel": "low",
                },
            },
        ),
        _record(
            "context.compiled",
            2,
            {"prompt": "secret compiled prompt", "systemPrompt": "tool inventory"},
        ),
        _record("prompt.submitted", 3, {"prompt": "Run the engineering heartbeat"}),
        _record(
            "model.completed",
            4,
            {
                "aborted": False,
                "timedOut": False,
                "idleTimedOut": False,
                "assistantTexts": ["Heartbeat complete."],
                "usage": {"total": 399242},
            },
        ),
        _record(
            "trace.artifacts",
            5,
            {
                "capturedAt": "2026-05-01T03:04:36.759Z",
                "finalStatus": "success",
                "toolMetas": [
                    {"toolName": "exec", "meta": "date -u +%F"},
                    {"toolName": "sessions_spawn", "meta": "spawn the reviewer"},
                ],
            },
        ),
        _record("session.ended", 6, {"status": "success", "aborted": False}),
    ]
    return "\n".join(json.dumps(record) for record in records)


class TestOpenClawTrajectoryParser:
    def test_parses_success_heartbeat_into_canonical_events(self):
        events = OpenClawTrajectoryParser().parse(_success_trajectory())

        actions = [event.action for event in events]
        assert actions == [
            "session_started",
            "model_snapshot",
            "user_message",
            "model_completed",
            "exec",
            "sessions_spawn",
            "session_ended",
        ]
        assert all(event.session_id == SESSION_ID for event in events)

        user = events[2]
        assert user.event_type == EventType.OUTPUT
        assert user.outputs["text"] == "Run the engineering heartbeat"

        completed = events[3]
        assert completed.outputs["text"] == "Heartbeat complete."
        assert "error" not in completed.outputs
        assert completed.metadata["token_total"] == 399242

        tool = events[4]
        assert tool.event_type == EventType.TOOL_CALL
        assert tool.inputs == {"meta": "date -u +%F"}
        assert tool.metadata["semantic_action_category"] == "shell"

        handoff = events[5]
        assert handoff.event_type == EventType.HANDOFF

        ended = events[6]
        assert ended.outputs["status"] == "success"
        assert "error" not in ended.outputs

    def test_success_run_carries_no_failure_context(self):
        events = OpenClawTrajectoryParser().parse(_success_trajectory())
        assert all(event.failure_context is None for event in events)

    def test_context_compiled_content_never_becomes_an_event(self):
        events = OpenClawTrajectoryParser().parse(_success_trajectory())
        serialised = json.dumps(
            [
                {"inputs": event.inputs, "outputs": event.outputs}
                for event in events
            ]
        )
        assert "secret compiled prompt" not in serialised
        assert "tool inventory" not in serialised

    def test_timed_out_model_call_yields_failure_context(self):
        records = [
            _record("prompt.submitted", 0, {"prompt": "do the thing"}),
            _record(
                "model.completed",
                1,
                {"aborted": False, "timedOut": True, "assistantTexts": []},
            ),
            _record("session.ended", 2, {"status": "error"}),
        ]
        content = "\n".join(json.dumps(record) for record in records)

        events = OpenClawTrajectoryParser().parse(content)

        completed = next(e for e in events if e.action == "model_completed")
        assert completed.outputs["error"] == "run timed out"
        assert completed.outputs["is_error"] is True
        assert completed.failure_context is not None
        assert completed.failure_context["status"] == "error"

        ended = next(e for e in events if e.action == "session_ended")
        assert ended.outputs["error"] == "session ended with status error"
        assert ended.failure_context is not None

    def test_failed_final_status_emits_run_outcome_event(self):
        records = [
            _record(
                "trace.artifacts",
                0,
                {
                    "finalStatus": "error",
                    "promptErrorSource": "rate_limit",
                    "toolMetas": [],
                },
            ),
        ]
        events = OpenClawTrajectoryParser().parse(
            "\n".join(json.dumps(record) for record in records)
        )

        assert [event.action for event in events] == ["run_outcome"]
        outcome = events[0]
        assert outcome.outputs["status"] == "error"
        assert outcome.outputs["error"] == "prompt error: rate_limit"
        assert outcome.failure_context is not None

    def test_unknown_record_types_and_bad_lines_are_skipped(self):
        content = "\n".join(
            [
                "not json at all",
                json.dumps(_record("trace.future-thing", 0, {"x": 1})),
                json.dumps(_record("prompt.submitted", 1, {"prompt": "hello"})),
            ]
        )
        events = OpenClawTrajectoryParser().parse(content)
        assert [event.action for event in events] == ["user_message"]

    def test_empty_content_parses_to_no_events(self):
        assert OpenClawTrajectoryParser().parse("") == []

    def test_ordering_is_stable_from_seq_with_synthetic_timestamps(self):
        events = OpenClawTrajectoryParser().parse(_success_trajectory())
        timestamps = [event.timestamp for event in events]
        assert timestamps == sorted(timestamps)
        # Base time anchors on the earliest capturedAt in the file.
        assert timestamps[0].isoformat().startswith("2026-05-01T03:00:00")

    def test_source_type(self):
        assert OpenClawTrajectoryParser().source_type == "openclaw_trajectory"

    def test_out_of_order_records_are_sorted_by_seq(self):
        """A trajectory emitted or concatenated out of file order must still
        produce the seq-ordered event chain (reviewer repro on PR 140)."""
        records = [
            _record(
                "model.completed", 4, {"assistantTexts": ["done"], "aborted": False}
            ),
            _record("prompt.submitted", 3, {"prompt": "do the thing"}),
            _record("session.started", 0, {"agentId": "engineering"}),
        ]
        content = "\n".join(json.dumps(record) for record in records)

        events = OpenClawTrajectoryParser().parse(content)

        assert [event.action for event in events] == [
            "session_started",
            "user_message",
            "model_completed",
        ]
        timestamps = [event.timestamp for event in events]
        assert timestamps == sorted(timestamps)
        # The parent chain follows seq order, not file order.
        assert events[1].parent_event_id == events[0].id
        assert events[2].parent_event_id == events[1].id

    def test_records_without_seq_keep_file_order(self):
        records = [
            _record("session.started", 0, {"agentId": "engineering"}),
            _record("prompt.submitted", 1, {"prompt": "first"}),
        ]
        for record in records:
            del record["seq"]
        content = "\n".join(json.dumps(record) for record in records)

        events = OpenClawTrajectoryParser().parse(content)

        assert [event.action for event in events] == [
            "session_started",
            "user_message",
        ]
