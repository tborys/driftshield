"""Golden analysis regression tests for anonymized dogfood transcript corpus."""

import json
from pathlib import Path

from driftshield.core.analysis.session import analyze_session
from driftshield.parsers.claude_code import ClaudeCodeParser


TRANSCRIPTS_DIR = Path(__file__).parent.parent.parent / "fixtures" / "transcripts"
GOLDEN_PATH = TRANSCRIPTS_DIR / "golden" / "dogfood_corpus_expectations.json"


def _load_fixtures() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text())["fixtures"]


def test_dogfood_analysis_golden_regressions():
    parser = ClaudeCodeParser()

    for fixture in _load_fixtures():
        events = parser.parse_file(str(TRANSCRIPTS_DIR / fixture["path"]))
        result = analyze_session(events)

        assert result.total_events == fixture["expected"]["event_count"], fixture["name"]
        assert result.risk_summary == fixture["expected"]["risk_summary"], fixture["name"]

        expected_has_risks = any(v > 0 for v in fixture["expected"]["risk_summary"].values())
        assert result.has_risks is expected_has_risks, fixture["name"]
