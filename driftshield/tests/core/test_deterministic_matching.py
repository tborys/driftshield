from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.deterministic_matching import (
    MATCHING_SCHEMA_VERSION,
    RULESET_VERSION,
    build_deterministic_match,
    build_signature_match_summary,
)
from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import CanonicalEvent, EventType, RiskClassification

# meta#302 / meta#296 round-2 Nit 2: the public matcher version constants must
# never carry an internal identifier. Forbidden case-insensitive substrings plus
# a 7+ contiguous hex run (catches leaked build SHAs). Mirrors the boundary gate
# in scripts/check-public-scope.sh.
#
# The two employer tokens are assembled from fragments so this public test file
# never spells them out as a contiguous string, exactly as the boundary gate
# stores them as hashes. The substring check below still matches the full token.
_FORBIDDEN_SUBSTRINGS = (
    "bal" + "ly",
    "game" + "sys",
    "internal",
    "private",
)
_HEX_RUN_RE = re.compile(r"[0-9a-fA-F]{7,}")


# Parametrise on the constant NAME only, never the value. A failing run in
# public CI must not republish the offending token, and pytest leaks a
# parametrised value three ways: the test id, the assert-rewrite introspection,
# and the message. So: the value is looked up inside the test (never in the id),
# and we use an explicit pytest.fail() with a redacted message instead of a
# rewritten `assert token not in value` (which would print both). meta#302 review.
_GUARDED_CONSTANTS = {
    "MATCHING_SCHEMA_VERSION": MATCHING_SCHEMA_VERSION,
    "RULESET_VERSION": RULESET_VERSION,
}


@pytest.mark.parametrize("constant_name", sorted(_GUARDED_CONSTANTS))
def test_matcher_version_constant_has_no_internal_identifier(constant_name):
    constant_value = _GUARDED_CONSTANTS[constant_name]
    lowered = constant_value.lower()
    for index, forbidden in enumerate(_FORBIDDEN_SUBSTRINGS):
        if forbidden in lowered:
            pytest.fail(
                f"{constant_name} carries a forbidden internal identifier "
                f"(forbid-list rule #{index}); token and value redacted from "
                f"this public log. See scripts/check-public-scope.sh forbid-list."
            )
    if _HEX_RUN_RE.search(constant_value) is not None:
        pytest.fail(
            f"{constant_name} carries a 7+ hex-char run (looks like a leaked "
            f"build SHA); value redacted from this public log."
        )


def _analysis_result(*, risk: RiskClassification | None = None) -> AnalysisResult:
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id="session-1",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="agent-1",
        action="test",
        risk_classification=risk,
    )
    return AnalysisResult(
        events=[event],
        graph=LineageGraph(session_id="session-1"),
        inflection_node=None,
        total_events=1,
        flagged_events=1 if risk and risk.has_any_flag() else 0,
        inflection_explanation=None,
    )


def test_deterministic_matching_surfaces_verification_failure_candidates():
    canonical_analysis = {
        "analysis_session": {"integrity_status": "complete", "source_provenance": {"source_type": "claude_code"}},
        "normalized_events": [
            {
                "event_id": "evt-tool",
                "sequence_index": 0,
                "event_family": "tool_call",
                "structured_payload": {"safety_relevant_flags": ["mutates_state"], "tool_category": "filesystem"},
            },
            {
                "event_id": "evt-out",
                "sequence_index": 1,
                "event_family": "output_emission",
                "structured_payload": {},
            },
        ],
        "run_context": {},
        "policy_and_instruction_context": {
            "system_constraints": [{"constraint": "Ask for confirmation before destructive changes."}],
            "developer_constraints": [],
            "user_constraints": [],
            "derived_operational_constraints": [],
            "conflict_or_shadowing_notes": [],
        },
        "expected_vs_actual_delta": {"delta_types": ["wrong_action"], "supporting_event_ids": ["evt-tool"]},
        "extraction_quality_summary": {"overall_quality_band": "usable", "ordering_confidence": 1.0, "ambiguity_count": 0},
    }

    payload = build_deterministic_match(canonical_analysis=canonical_analysis, result=_analysis_result())
    summary = build_signature_match_summary(payload)

    assert payload["status"] == "matched"
    assert payload["matched_rules"][0]["rule_id"] == "R-VER-001"
    assert payload["matched_sequence_patterns"][0]["sequence_id"] == "SEQ-VER-001"
    assert payload["candidate_signatures"][0]["signature_key"] == "verification_failure"
    assert payload["candidate_signatures"][0]["deterministic_score"] > 0.6
    assert summary["primary_mechanism_id"] == "verification_failure"
    assert summary["matches"][0]["signature_id"] == "mechanism:verification_failure"


def test_deterministic_matching_does_not_flag_verification_failure_without_requirement():
    canonical_analysis = {
        "analysis_session": {"integrity_status": "complete", "source_provenance": {"source_type": "claude_code"}},
        "normalized_events": [
            {
                "event_id": "evt-tool",
                "sequence_index": 0,
                "event_family": "tool_call",
                "structured_payload": {"safety_relevant_flags": ["mutates_state"], "tool_category": "filesystem"},
            },
            {
                "event_id": "evt-out",
                "sequence_index": 1,
                "event_family": "output_emission",
                "structured_payload": {},
            },
        ],
        "run_context": {},
        "policy_and_instruction_context": {
            "system_constraints": [],
            "developer_constraints": [],
            "user_constraints": [],
            "derived_operational_constraints": [],
            "conflict_or_shadowing_notes": [],
        },
        "expected_vs_actual_delta": {"delta_types": [], "supporting_event_ids": ["evt-tool"]},
        "extraction_quality_summary": {"overall_quality_band": "usable", "ordering_confidence": 1.0, "ambiguity_count": 0},
    }

    payload = build_deterministic_match(canonical_analysis=canonical_analysis, result=_analysis_result())

    assert payload["status"] == "unclassified"
    assert payload["matched_rules"] == []
    assert payload["matched_sequence_patterns"] == []
    assert payload["candidate_signatures"] == []
    assert payload["extracted_features"]["safeguard_requirement_present"] is False
    assert payload["extracted_features"]["safeguard_omitted"] is False



def test_deterministic_matching_marks_ambiguity_and_degraded_quality():
    canonical_analysis = {
        "analysis_session": {"integrity_status": "complete", "source_provenance": {"source_type": "claude_code"}},
        "normalized_events": [
            {
                "event_id": "evt-out",
                "sequence_index": 0,
                "event_family": "output_emission",
                "structured_payload": {},
            }
        ],
        "run_context": {},
        "policy_and_instruction_context": {
            "system_constraints": [],
            "developer_constraints": [],
            "user_constraints": [],
            "derived_operational_constraints": [],
            "conflict_or_shadowing_notes": [],
        },
        "expected_vs_actual_delta": {
            "delta_types": ["missing_required_action", "retrieval_failure_or_omission", "unresolved_ambiguity"],
            "supporting_event_ids": ["evt-out"],
        },
        "extraction_quality_summary": {
            "overall_quality_band": "degraded",
            "ordering_confidence": 0.5,
            "ambiguity_count": 2,
        },
    }

    payload = build_deterministic_match(canonical_analysis=canonical_analysis, result=_analysis_result())

    assert payload["status"] == "matched"
    assert payload["unresolved_ambiguity_flag"] is True
    assert payload["quality_flags"] == []
    assert [candidate["signature_key"] for candidate in payload["candidate_signatures"]] == [
        "retrieval_omission",
        "coverage_gap",
    ]
    assert all("quality_degraded" in candidate["confidence_notes"] for candidate in payload["candidate_signatures"])


def test_deterministic_matching_records_contradictions_for_tool_misuse():
    canonical_analysis = {
        "analysis_session": {"integrity_status": "complete", "source_provenance": {"source_type": "claude_code"}},
        "normalized_events": [
            {
                "event_id": "evt-tool-result",
                "sequence_index": 0,
                "event_family": "tool_result",
                "structured_payload": {"result_status": "error", "tool_category": "shell"},
            },
            {
                "event_id": "evt-out",
                "sequence_index": 1,
                "event_family": "output_emission",
                "structured_payload": {},
            },
        ],
        "run_context": {},
        "policy_and_instruction_context": {
            "system_constraints": [],
            "developer_constraints": [],
            "user_constraints": [],
            "derived_operational_constraints": [],
            "conflict_or_shadowing_notes": [],
        },
        "expected_vs_actual_delta": {"delta_types": ["tool_misuse"], "supporting_event_ids": ["evt-tool-result"]},
        "extraction_quality_summary": {"overall_quality_band": "usable", "ordering_confidence": 1.0, "ambiguity_count": 0},
    }

    payload = build_deterministic_match(canonical_analysis=canonical_analysis, result=_analysis_result())
    candidate = payload["candidate_signatures"][0]

    assert candidate["signature_key"] == "tool_misuse"
    assert candidate["contradicting_evidence"] == [
        {"feature_ref": "expected_vs_actual_delta_types", "flag": "no_schema_mismatch_detected"}
    ]
    assert candidate["deterministic_score"] <= 0.6


def test_deterministic_matching_rejects_insufficient_structure():
    payload = build_deterministic_match(canonical_analysis={"normalized_events": []}, result=_analysis_result())

    assert payload["status"] == "insufficient_evidence"
    assert "missing_domain:analysis_session" in payload["integrity_flags"]
    assert "no_normalized_events" in payload["integrity_flags"]
