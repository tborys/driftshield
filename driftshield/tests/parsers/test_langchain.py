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

    def test_source_type_is_langchain(self):
        parser = LangChainParser()
        assert parser.source_type == "langchain"
