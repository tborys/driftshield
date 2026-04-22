"""Phase 2b normalized event pipeline coverage."""

from pathlib import Path

import pytest

from driftshield.core.analysis.session import analyze_session
from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.codex_cli import CodexCliParser
from driftshield.parsers.crewai import CrewAIParser
from driftshield.parsers.langchain import LangChainParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


@pytest.mark.parametrize(
    ("parser", "fixture_name", "expected_parser"),
    [
        (ClaudeCodeParser(), "sample_claude_code_session.jsonl", "claude_code"),
        (LangChainParser(), "sample_langchain_session.json", "langchain"),
        (CrewAIParser(), "sample_crewai_session.json", "crewai"),
        (CodexCliParser(), "sample_codex_cli_session.jsonl", "codex_cli"),
    ],
)
def test_supported_parser_fixtures_share_normalized_event_contract(
    parser,
    fixture_name,
    expected_parser,
):
    events = parser.parse_file(str(FIXTURES_DIR / fixture_name))

    assert events
    for index, event in enumerate(events):
        assert event.ordinal == index
        assert event.summary
        assert event.actor is not None
        assert event.actor["id"]
        assert any(
            ref["kind"] == "parser" and ref["value"] == expected_parser
            for ref in event.source_refs
        )
        payload = event.to_normalized_dict()
        assert payload["event_id"] == str(event.id)
        assert payload["event_kind"]
        assert payload["summary"] == event.summary


def test_normalized_pipeline_preserves_constraints_and_failure_context():
    crewai_events = CrewAIParser().parse_file(str(FIXTURES_DIR / "sample_crewai_session.json"))
    langchain_events = LangChainParser().parse_file(str(FIXTURES_DIR / "sample_langchain_session.json"))

    crewai_tool_event = next(event for event in crewai_events if event.tool_activity is not None)
    langchain_tool_event = next(event for event in langchain_events if event.tool_activity is not None)

    assert {"kind": "expected_output", "value": "A short list of concrete risks.", "source": "inputs"} in crewai_tool_event.constraints
    assert langchain_tool_event.failure_context == {
        "status": "error",
        "error": "permission warning preserved for analysis",
        "signals": ["explicit_error"],
        "declared_failure": True,
    }


@pytest.mark.parametrize(
    ("parser", "fixture_name"),
    [
        (ClaudeCodeParser(), "sample_claude_code_session.jsonl"),
        (LangChainParser(), "sample_langchain_session.json"),
        (CrewAIParser(), "sample_crewai_session.json"),
    ],
)
def test_analysis_consumes_normalized_parser_output_without_parser_specific_branching(
    parser,
    fixture_name,
):
    events = parser.parse_file(str(FIXTURES_DIR / fixture_name))

    result = analyze_session(events)

    assert result.events
    assert [event.ordinal for event in result.events] == list(range(len(result.events)))
    assert [node.sequence_num for node in result.graph.nodes] == list(range(len(result.graph.nodes)))
