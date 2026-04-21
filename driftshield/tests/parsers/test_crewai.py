"""Tests for the CrewAI transcript parser."""

import json
from pathlib import Path

from driftshield.core.models import EventType
from driftshield.parsers.crewai import CrewAIParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestCrewAIParser:
    def test_parses_representative_crewai_export_fixture(self):
        parser = CrewAIParser()
        events = parser.parse_file(str(FIXTURES_DIR / "sample_crewai_session.json"))

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
        assert all(event.session_id == "crewai-run-001" for event in events)
        assert events[0].outputs["text"] == "Inspect the README and identify obvious risks."
        assert events[1].inputs["tool_input"] == {"file_path": "README.md"}
        assert events[1].outputs["result"] == {
            "content": "# DriftShield\nA decision forensics platform."
        }
        assert events[2].outputs["text"] == "The README is present and the main risk is missing setup detail."

    def test_parse_accepts_direct_payload_string(self):
        parser = CrewAIParser()
        payload = {
            "run_id": "crewai-inline",
            "input": "Check parser support.",
            "started_at": "2026-04-21T02:25:00Z",
            "tasks": [
                {
                    "id": "task-inline",
                    "name": "lookup_notes",
                    "description": "Lookup parser notes",
                    "status": "completed",
                    "started_at": "2026-04-21T02:25:01Z",
                    "completed_at": "2026-04-21T02:25:03Z",
                    "agent": {"role": "analyst", "goal": "Check notes"},
                    "tool_calls": [
                        {
                            "tool_name": "search_notes",
                            "input": {"query": "parser support"},
                            "output": {"status": "ok"},
                            "error": None,
                        }
                    ],
                    "output": "Parser notes found.",
                }
            ],
        }

        events = parser.parse(json.dumps(payload))

        assert len(events) == 3
        assert events[0].session_id == "crewai-inline"
        assert events[1].action == "search_notes"
        assert events[1].outputs["result"] == {"status": "ok"}
        assert events[2].outputs["text"] == "Parser notes found."

    def test_emits_one_event_per_tool_call_within_task(self):
        parser = CrewAIParser()
        payload = {
            "run_id": "crewai-multi-tool",
            "input": "Inspect docs and config.",
            "started_at": "2026-04-21T02:30:00Z",
            "tasks": [
                {
                    "id": "task-multi",
                    "name": "inspect_repo",
                    "description": "Inspect docs and config",
                    "status": "completed",
                    "started_at": "2026-04-21T02:30:01Z",
                    "completed_at": "2026-04-21T02:30:04Z",
                    "agent": {"role": "researcher", "goal": "Inspect files"},
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "input": {"file_path": "README.md"},
                            "output": {"content": "# README"},
                            "error": None,
                        },
                        {
                            "tool_name": "read_file",
                            "input": {"file_path": "pyproject.toml"},
                            "output": {"content": "[project]"},
                            "error": None,
                        },
                    ],
                    "output": "Repo inspection completed.",
                }
            ],
        }

        events = parser.parse(json.dumps(payload))

        assert [event.action for event in events] == [
            "user_message",
            "read_file",
            "read_file",
            "assistant_narrative",
        ]
        assert events[1].inputs["tool_input"] == {"file_path": "README.md"}
        assert events[1].outputs["result"] == {"content": "# README"}
        assert events[1].metadata["tool_call_index"] == 0
        assert events[2].inputs["tool_input"] == {"file_path": "pyproject.toml"}
        assert events[2].outputs["result"] == {"content": "[project]"}
        assert events[2].metadata["tool_call_index"] == 1

    def test_source_type_is_crewai(self):
        parser = CrewAIParser()
        assert parser.source_type == "crewai"
