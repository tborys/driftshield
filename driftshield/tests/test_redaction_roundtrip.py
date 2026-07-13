"""Round-trip + safety tests for driftshield#158.

Reproduces the hosted intake path against a real Claude Code JSONL fixture:
``load_session_payload`` -> ``build_redacted_payload`` -> flatten
``payload["events"]`` back to JSONL -> ``analyse(source="auto")``. Before the
fix, the recursive redactor dropped every ``content``/``text`` key wholesale,
so this path lost every tool_use/tool_result/text record and the hosted
verdict silently degraded to ``not_classifiable`` with zero tool_call events.
"""

from __future__ import annotations

import json
from pathlib import Path

from driftshield.cli._session_payload import load_session_payload
from driftshield.public import analyse
from driftshield.remote_submission import build_redacted_payload

_FIXTURE = Path(__file__).parent / "fixtures" / "transcripts" / "sample_claude_code_session.jsonl"

# Mirrors recursive_redactor._FAILURE_BODY_KEYS: the intel backstop
# (scan_payload_for_unredacted) refuses these keys on presence, so they must
# never reappear in a redacted payload.
_BACKSTOP_REFUSED_KEYS = ("toolUseResult", "stdout", "stderr", "error", "details", "raw")


def _flatten_to_jsonl(payload: dict) -> str:
    return "\n".join(json.dumps(event) for event in payload["events"])


def _tool_call_count(analyse_result: dict) -> int:
    events = analyse_result["canonical_analysis"]["normalized_events"]
    return sum(1 for event in events if event["event_type"] == "tool_call")


def _raw_prompt_response_bodies(value: object) -> list[str]:
    """Collect every string under a ``content``/``text``/tool_use ``input`` key.

    Used to assert none of the pre-redaction free text or tool-argument
    values survive verbatim in the redacted payload.
    """
    bodies: list[str] = []

    def walk(node: object, under_sensitive_key: bool) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                sensitive = under_sensitive_key or key in ("content", "text", "input")
                if key in ("content", "text", "input") and isinstance(item, str) and len(item) > 20:
                    bodies.append(item)
                walk(item, sensitive)
        elif isinstance(node, list):
            for item in node:
                walk(item, under_sensitive_key)

    walk(value, False)
    return bodies


def test_round_trip_preserves_tool_call_count_and_classifiable_verdict():
    raw_content = _FIXTURE.read_text()
    raw_result = analyse(raw_content, source="auto")
    assert raw_result["source_format"] == "claude_code"
    assert raw_result["qualification"]["qualification_state"] != "not_classifiable"
    raw_tool_calls = _tool_call_count(raw_result)
    assert raw_tool_calls > 0

    payload = load_session_payload(_FIXTURE)
    redacted_payload = build_redacted_payload(payload=payload)
    redacted_content = _flatten_to_jsonl(redacted_payload)

    redacted_result = analyse(redacted_content, source="auto")
    assert redacted_result["source_format"] == "claude_code"
    assert redacted_result["qualification"]["qualification_state"] != "not_classifiable"
    assert _tool_call_count(redacted_result) == raw_tool_calls


def test_redaction_safety_no_backstop_refused_keys_no_raw_bodies():
    payload = load_session_payload(_FIXTURE)
    redacted_payload = build_redacted_payload(payload=payload)
    serialised = json.dumps(redacted_payload)

    for key in _BACKSTOP_REFUSED_KEYS:
        assert f'"{key}"' not in serialised, f"backstop-refused key {key!r} survived redaction"

    raw_bodies = _raw_prompt_response_bodies(payload)
    assert raw_bodies, "fixture sanity check: expected at least one prompt/response body"
    for body in raw_bodies:
        assert body not in serialised, "raw prompt/response or tool-input text leaked verbatim"


def test_analyse_does_not_raise_on_legacy_tool_use_input_string_placeholder():
    """Already-uploaded ruleset.v2 payloads redacted a tool_use ``input`` to a
    STRING placeholder (``_TOOL_IO_KEYS`` generic rule). A re-parse of that
    already-uploaded shape must not raise ``AttributeError`` in
    ``heuristics._find_lists_in_dict`` (or anywhere else ``event.inputs`` is
    read as a mapping).
    """
    entry = {
        "sessionId": "legacy-session",
        "type": "assistant",
        "timestamp": "2026-07-01T00:00:00Z",
        "message": {
            "model": "claude",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_legacy",
                    "name": "read_file",
                    "input": "<REDACTED:tool_io:deadbeefcafefeed>",
                }
            ],
        },
    }
    content = json.dumps(entry)

    result = analyse(content, source="claude_code")

    assert result["source_format"] == "claude_code"
    assert result["event_count"] >= 1
