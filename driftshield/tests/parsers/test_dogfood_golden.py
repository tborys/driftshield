"""Golden parser regression tests for anonymized dogfood transcript corpus."""

import json
from collections import Counter
from pathlib import Path

from driftshield.parsers.claude_code import ClaudeCodeParser


TRANSCRIPTS_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"
GOLDEN_PATH = TRANSCRIPTS_DIR / "golden" / "dogfood_corpus_expectations.json"


def _load_fixtures() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text())["fixtures"]


def test_dogfood_parser_golden_regressions():
    parser = ClaudeCodeParser()

    for fixture in _load_fixtures():
        events = parser.parse_file(str(TRANSCRIPTS_DIR / fixture["path"]))

        assert len(events) == fixture["expected"]["event_count"], fixture["name"]

        event_types = Counter(e.event_type.value for e in events)
        assert dict(event_types) == fixture["expected"]["event_types"], fixture["name"]

        assert all(e.session_id for e in events), fixture["name"]
        assert all(e.timestamp is not None for e in events), fixture["name"]

        # Handoff fields are not currently extracted by parser (future issue scope).
        has_handoff = any(e.metadata.get("handoff") for e in events if e.metadata)
        assert has_handoff is fixture["expected"]["has_handoff"], fixture["name"]
