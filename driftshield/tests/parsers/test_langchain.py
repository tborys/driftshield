"""Tests for the LangChain transcript parser."""

import json
from pathlib import Path

from driftshield.core.models import EventType
from driftshield.parsers.langchain import LangChainParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestLangChainParser:
    def test_parses_representative_langsmith_export_fixture(self):
        parser = LangChainParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_langchain_session.json"))

        assert [event.event_type for event in events] == [
            EventType.OUTPUT,
            EventType.TOOL_CALL,
            EventType.OUTPUT,
        ]
        assert [event.action for event in events] == [
            "user_message",
            "read_file",
            "assistant_narrative",
        ]
        assert all(event.session_id == "trace-issue-11" for event in events)
        assert events[0].outputs["text"] == "Please inspect the README and summarise the risks."
        assert events[1].inputs == {"file_path": "README.md"}
        assert events[1].outputs["result"] == {"content": "# DriftShield"}
        assert events[1].outputs["error"] == "permission warning preserved for analysis"
        assert events[1].metadata["semantic_action_category"] == "other"
        assert events[2].outputs["text"] == "I inspected the README and found no immediate risks."

    def test_parse_accepts_single_root_object_with_child_runs(self):
        parser = LangChainParser()
        payload = {
            "id": "root-run",
            "trace_id": "trace-single-object",
            "name": "AgentExecutor",
            "run_type": "chain",
            "start_time": "2026-04-19T09:00:00Z",
            "end_time": "2026-04-19T09:00:03Z",
            "inputs": {
                "messages": [{"role": "human", "content": "Check parser wiring."}]
            },
            "outputs": {
                "messages": [{"role": "ai", "content": "Parser wiring looks good."}]
            },
            "child_runs": [
                {
                    "id": "tool-run",
                    "trace_id": "trace-single-object",
                    "parent_run_id": "root-run",
                    "name": "lookup_fixture",
                    "run_type": "tool",
                    "start_time": "2026-04-19T09:00:01Z",
                    "inputs": {"path": "tests/fixtures/transcripts/sample_langchain_session.json"},
                    "outputs": {"status": "ok"},
                    "error": None,
                }
            ],
        }

        events = parser.parse(json.dumps(payload))

        assert len(events) == 3
        assert events[0].session_id == "trace-single-object"
        assert events[1].action == "lookup_fixture"
        assert events[1].outputs["result"] == {"status": "ok"}
        assert events[2].outputs["text"] == "Parser wiring looks good."

    def test_orders_tool_runs_by_execution_order_when_available(self):
        parser = LangChainParser()
        payload = [
            {
                "id": "root",
                "trace_id": "trace-ordering",
                "name": "AgentExecutor",
                "run_type": "chain",
                "start_time": "2026-04-19T10:00:00Z",
                "inputs": {"messages": [{"role": "human", "content": "Do two tool calls."}]},
                "outputs": {"messages": [{"role": "ai", "content": "Done."}]},
            },
            {
                "id": "tool-late",
                "trace_id": "trace-ordering",
                "parent_run_id": "root",
                "name": "second_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T10:00:03Z",
                "execution_order": 20,
                "inputs": {},
                "outputs": {"status": "second"},
            },
            {
                "id": "tool-early",
                "trace_id": "trace-ordering",
                "parent_run_id": "root",
                "name": "first_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T10:00:04Z",
                "execution_order": 10,
                "inputs": {},
                "outputs": {"status": "first"},
            },
        ]

        events = parser.parse(json.dumps(payload))

        assert [event.action for event in events] == [
            "user_message",
            "first_tool",
            "second_tool",
            "assistant_narrative",
        ]

    def test_filters_out_other_roots_and_traces_from_same_export(self):
        parser = LangChainParser()
        payload = [
            {
                "id": "root-a",
                "trace_id": "trace-a",
                "name": "AgentExecutor",
                "run_type": "chain",
                "start_time": "2026-04-19T11:00:00Z",
                "inputs": {"messages": [{"role": "human", "content": "Inspect README."}]},
                "outputs": {"messages": [{"role": "ai", "content": "README inspected."}]},
            },
            {
                "id": "tool-a",
                "trace_id": "trace-a",
                "parent_run_id": "root-a",
                "name": "read_file",
                "run_type": "tool",
                "start_time": "2026-04-19T11:00:01Z",
                "inputs": {"file_path": "README.md"},
                "outputs": {"status": "ok"},
            },
            {
                "id": "root-b",
                "trace_id": "trace-b",
                "name": "OtherRoot",
                "run_type": "chain",
                "start_time": "2026-04-19T11:00:02Z",
                "inputs": {"messages": [{"role": "human", "content": "Ignore this trace."}]},
                "outputs": {"messages": [{"role": "ai", "content": "Ignored."}]},
            },
            {
                "id": "tool-b",
                "trace_id": "trace-b",
                "parent_run_id": "root-b",
                "name": "foreign_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T11:00:03Z",
                "inputs": {"file_path": "OTHER.md"},
                "outputs": {"status": "foreign"},
            },
        ]

        events = parser.parse(json.dumps(payload))

        assert [event.action for event in events] == [
            "user_message",
            "read_file",
            "assistant_narrative",
        ]
        assert all(event.session_id == "trace-a" for event in events)
        assert all(event.metadata.get("trace_id") != "trace-b" for event in events if event.event_type == EventType.TOOL_CALL)

    def test_orders_hierarchical_dotted_order_safely(self):
        parser = LangChainParser()
        payload = [
            {
                "id": "root",
                "trace_id": "trace-dotted-order",
                "name": "AgentExecutor",
                "run_type": "chain",
                "start_time": "2026-04-19T12:00:00Z",
                "inputs": {"messages": [{"role": "human", "content": "Run nested tools."}]},
                "outputs": {"messages": [{"role": "ai", "content": "Nested tools done."}]},
            },
            {
                "id": "tool-2-1",
                "trace_id": "trace-dotted-order",
                "parent_run_id": "root",
                "name": "later_branch_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T12:00:03Z",
                "dotted_order": "2.1",
                "inputs": {},
                "outputs": {"status": "later"},
            },
            {
                "id": "tool-1-10",
                "trace_id": "trace-dotted-order",
                "parent_run_id": "root",
                "name": "earlier_branch_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T12:00:04Z",
                "dotted_order": "1.10",
                "inputs": {},
                "outputs": {"status": "earlier"},
            },
        ]

        events = parser.parse(json.dumps(payload))

        assert [event.action for event in events] == [
            "user_message",
            "earlier_branch_tool",
            "later_branch_tool",
            "assistant_narrative",
        ]

    def test_orders_native_langsmith_dotted_order_safely(self):
        parser = LangChainParser()
        payload = [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "trace_id": "trace-native-dotted",
                "name": "root",
                "run_type": "chain",
                "start_time": "2026-04-19T12:00:00Z",
                "inputs": {"messages": [{"role": "human", "content": "Run tools"}]},
                "outputs": {"messages": [{"role": "ai", "content": "Done"}]},
                "dotted_order": "20260419T120000000000Z00000000-0000-0000-0000-000000000001",
            },
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "trace_id": "trace-native-dotted",
                "parent_run_id": "00000000-0000-0000-0000-000000000001",
                "name": "second_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T12:00:01Z",
                "inputs": {},
                "outputs": {"status": "second"},
                "dotted_order": "20260419T120000000000Z00000000-0000-0000-0000-000000000001.20260419T120002000000Z00000000-0000-0000-0000-000000000002",
            },
            {
                "id": "00000000-0000-0000-0000-000000000010",
                "trace_id": "trace-native-dotted",
                "parent_run_id": "00000000-0000-0000-0000-000000000001",
                "name": "first_tool",
                "run_type": "tool",
                "start_time": "2026-04-19T12:00:01Z",
                "inputs": {},
                "outputs": {"status": "first"},
                "dotted_order": "20260419T120000000000Z00000000-0000-0000-0000-000000000001.20260419T120001000000Z00000000-0000-0000-0000-000000000010",
            },
        ]

        events = parser.parse(json.dumps(payload))

        assert [event.action for event in events] == [
            "user_message",
            "first_tool",
            "second_tool",
            "assistant_narrative",
        ]

    def test_parses_epoch_millisecond_timestamps(self):
        parser = LangChainParser()
        payload = {
            "id": "root-ms",
            "trace_id": "trace-ms",
            "name": "root",
            "run_type": "chain",
            "start_time": 1713513600000,
            "end_time": 1713513603000,
            "inputs": {"messages": [{"role": "human", "content": "Run tools"}]},
            "outputs": {"messages": [{"role": "ai", "content": "Done"}]},
            "child_runs": [
                {
                    "id": "tool-ms",
                    "trace_id": "trace-ms",
                    "parent_run_id": "root-ms",
                    "name": "tool_ms",
                    "run_type": "tool",
                    "start_time": 1713513601000,
                    "inputs": {},
                    "outputs": {"status": "ok"},
                }
            ],
        }

        events = parser.parse(json.dumps(payload))

        assert len(events) == 3
        assert events[0].timestamp.isoformat() == "2024-04-19T08:00:00+00:00"
        assert events[1].timestamp.isoformat() == "2024-04-19T08:00:01+00:00"
        assert events[2].timestamp.isoformat() == "2024-04-19T08:00:03+00:00"

    def test_source_type_is_langchain(self):
        parser = LangChainParser()
        assert parser.source_type == "langchain"
