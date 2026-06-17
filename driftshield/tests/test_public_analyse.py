"""Tests for the public ``analyse`` entrypoint (driftshield#148).

``analyse`` is the stable, content based, DB free chain an external host (the
DriftShield intel cloud worker) calls to get the same verdict the local
dashboard produces. These tests pin the contract: content detection, verdict
parity (qualified_failure / unclassified / not_classifiable), the OSS safe
signature summary shape, and graceful handling of empty or unparseable input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield.public import ANALYSE_SCHEMA_VERSION, analyse, detect_source

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
_REAL_TRAJECTORY = FIXTURES / "sample_openclaw_trajectory.json"
_CLAUDE_CODE = FIXTURES / "sample_claude_code_session.jsonl"
_CONSTRAINT_VIOLATION = FIXTURES / "dogfood" / "constraint_violation_session.jsonl"
_POLICY_DIVERGENCE = FIXTURES / "dogfood" / "policy_divergence_session.jsonl"
_CLEAN = FIXTURES / "dogfood" / "clean_session.jsonl"


# --------------------------------------------------------------------------- #
# Content based source detection (the cloud has no file path to key on)
# --------------------------------------------------------------------------- #


def test_detect_real_openclaw_trajectory_wrapper() -> None:
    body = _REAL_TRAJECTORY.read_text()
    assert detect_source(body) == "openclaw_trajectory"


def test_detect_claude_code_with_leading_non_identifying_record() -> None:
    # The sample opens with a file-history-snapshot record before any
    # user/assistant line; detection must scan past it.
    body = _CLAUDE_CODE.read_text()
    assert detect_source(body) == "claude_code"


def test_detect_openclaw_trajectory_jsonl_lines() -> None:
    line = json.dumps(
        {"runId": "r", "traceId": "t", "schemaVersion": 1, "seq": 1, "source": "runtime", "type": "session.started"}
    )
    assert detect_source(line) == "openclaw_trajectory"


def test_detect_returns_none_for_unrecognised_content() -> None:
    assert detect_source('{"hello": "world"}') is None
    assert detect_source("not json at all") is None
    assert detect_source("") is None


# --------------------------------------------------------------------------- #
# Verdict parity with the local dashboard
# --------------------------------------------------------------------------- #


def test_real_aborted_run_is_unclassified_not_a_fake_match() -> None:
    # The real captured OSS payload is a user-aborted, tool-less run. Honest
    # verdict parity: unclassified, zero matches. NOT a fabricated abort match.
    out = analyse(_REAL_TRAJECTORY.read_text())
    assert out["source_format"] == "openclaw_trajectory"
    assert out["schema_version"] == ANALYSE_SCHEMA_VERSION
    assert out["qualification"]["qualification_state"] == "unclassified"
    assert out["signature_summary"]["matches"] == []
    assert out["event_count"] > 0
    assert out["canonical_analysis"] is not None


def test_real_failure_run_qualifies_and_matches() -> None:
    # A genuine failure transcript produces qualified_failure + >=1 match,
    # proving the matcher fires through the same chain (not just parsing).
    out = analyse(_CONSTRAINT_VIOLATION.read_text())
    assert out["qualification"]["qualification_state"] == "qualified_failure"
    matches = out["signature_summary"]["matches"]
    assert len(matches) >= 1
    entry = matches[0]
    # OSS safe shape: identification + provenance + status/confidence/band only.
    assert entry["signature_id"]
    assert entry["match_status"] == "matched"
    assert entry["confidence_band"] in {"high", "medium", "low", "very_low"}
    assert entry["community_pack_id"]
    assert entry["matcher_id"]


def test_policy_divergence_run_qualifies_and_matches() -> None:
    out = analyse(_POLICY_DIVERGENCE.read_text())
    assert out["qualification"]["qualification_state"] == "qualified_failure"
    assert len(out["signature_summary"]["matches"]) >= 1


def test_clean_run_has_no_matches() -> None:
    out = analyse(_CLEAN.read_text())
    assert out["signature_summary"]["matches"] == []


# --------------------------------------------------------------------------- #
# Robustness: never raise on bad input (ingest must not 500)
# --------------------------------------------------------------------------- #


def test_empty_content_returns_not_classifiable() -> None:
    out = analyse("")
    assert out["source_format"] == "raw"
    assert out["qualification"]["qualification_state"] == "not_classifiable"
    assert out["signature_summary"]["matches"] == []
    assert out["event_count"] == 0


def test_unrecognised_content_returns_not_classifiable() -> None:
    out = analyse('{"some": "unknown shape"}')
    assert out["qualification"]["qualification_state"] == "not_classifiable"


def test_bytes_input_is_accepted() -> None:
    out = analyse(_REAL_TRAJECTORY.read_bytes())
    assert out["source_format"] == "openclaw_trajectory"


def test_explicit_source_overrides_detection() -> None:
    out = analyse(_REAL_TRAJECTORY.read_text(), source="openclaw_trajectory")
    assert out["source_format"] == "openclaw_trajectory"


def test_unsupported_explicit_source_returns_not_classifiable() -> None:
    out = analyse(_REAL_TRAJECTORY.read_text(), source="does_not_exist")
    assert out["source_format"] == "raw"
    assert out["qualification"]["qualification_state"] == "not_classifiable"


@pytest.mark.parametrize(
    "fixture",
    [_REAL_TRAJECTORY, _CLAUDE_CODE, _CONSTRAINT_VIOLATION, _CLEAN],
)
def test_signature_summary_is_serialisable(fixture: Path) -> None:
    # The whole verdict must round-trip through JSON (it is persisted as jsonb).
    out = analyse(fixture.read_text())
    json.dumps(out)
