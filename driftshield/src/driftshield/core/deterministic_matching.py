"""Phase 3g deterministic candidate generation over canonical analysed runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from driftshield.core.analysis.session import AnalysisResult

MATCHING_SCHEMA_VERSION = "phase-3g-deterministic-v1"
RULESET_VERSION = "phase-3g-deterministic-rules-v1"


@dataclass(frozen=True)
class CandidateDefinition:
    signature_key: str
    summary_template: str


_CANDIDATES: dict[str, CandidateDefinition] = {
    "coverage_gap": CandidateDefinition(
        signature_key="coverage_gap",
        summary_template="Missing required action or evidence before completion.",
    ),
    "verification_failure": CandidateDefinition(
        signature_key="verification_failure",
        summary_template="Safeguard or confirmation step was skipped before a risky action.",
    ),
    "policy_divergence": CandidateDefinition(
        signature_key="policy_divergence",
        summary_template="Observed action diverged from an explicit policy or instruction constraint.",
    ),
    "retrieval_omission": CandidateDefinition(
        signature_key="retrieval_omission",
        summary_template="Answer path omitted required retrieval evidence.",
    ),
    "state_conflict": CandidateDefinition(
        signature_key="state_conflict",
        summary_template="State transition evidence shows a conflicting or failed update.",
    ),
    "tool_misuse": CandidateDefinition(
        signature_key="tool_misuse",
        summary_template="Tool usage or tool outcome diverged from the expected contract.",
    ),
    "assumption_mutation": CandidateDefinition(
        signature_key="assumption_mutation",
        summary_template="Assistant-introduced assumption drove a later action without explicit user backing.",
    ),
}


def build_deterministic_match(
    *,
    canonical_analysis: dict[str, Any],
    result: AnalysisResult,
) -> dict[str, Any]:
    integrity_flags, quality_flags = _structural_flags(canonical_analysis)
    extracted_features = _extract_features(canonical_analysis, result)
    matched_rules = _match_rules(extracted_features, canonical_analysis, result)
    matched_sequence_patterns = _match_sequences(canonical_analysis, extracted_features)
    global_contradictions = _global_contradictions(extracted_features, canonical_analysis)
    candidate_signatures = _candidate_signatures(
        matched_rules=matched_rules,
        matched_sequence_patterns=matched_sequence_patterns,
        extracted_features=extracted_features,
        global_contradictions=global_contradictions,
    )
    unresolved_ambiguity_flag = _unresolved_ambiguity_flag(
        extracted_features=extracted_features,
        candidate_signatures=candidate_signatures,
        canonical_analysis=canonical_analysis,
    )

    return {
        "status": _status(
            integrity_flags=integrity_flags,
            quality_flags=quality_flags,
            candidate_signatures=candidate_signatures,
        ),
        "matching_schema_version": MATCHING_SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "integrity_flags": integrity_flags,
        "quality_flags": quality_flags,
        "extracted_features": extracted_features,
        "matched_rules": matched_rules,
        "matched_sequence_patterns": matched_sequence_patterns,
        "candidate_signatures": candidate_signatures,
        "global_contradictions": global_contradictions,
        "unresolved_ambiguity_flag": unresolved_ambiguity_flag,
    }


def build_signature_match_summary(deterministic_match: dict[str, Any]) -> dict[str, Any]:
    candidates = list(deterministic_match.get("candidate_signatures") or [])
    primary = candidates[0] if candidates else None
    summary = _summary_text(deterministic_match, primary)

    return {
        "status": deterministic_match.get("status"),
        "primary_mechanism_id": primary.get("signature_key") if isinstance(primary, dict) else None,
        "matched_mechanism_ids": [
            candidate.get("signature_key")
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("signature_key"), str)
        ],
        "match_count": len(candidates),
        "summary": summary,
        "matches": [
            {
                "match_id": f"deterministic:{candidate['signature_key']}:{candidate['candidate_rank']}",
                "signature_id": f"mechanism:{candidate['signature_key']}",
                "mechanism_id": candidate["signature_key"],
                "confidence": candidate.get("deterministic_score"),
                "summary": candidate.get("explanation_snippet"),
                "rationale": candidate.get("explanation_snippet"),
                "evidence_refs": [
                    evidence.get("event_id")
                    for evidence in candidate.get("supporting_evidence", [])
                    if isinstance(evidence, dict) and isinstance(evidence.get("event_id"), str)
                ],
                "source": "local_deterministic",
            }
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("signature_key"), str)
        ],
        "raw": deterministic_match,
    }


def _structural_flags(canonical_analysis: dict[str, Any]) -> tuple[list[str], list[str]]:
    integrity_flags: list[str] = []
    quality_flags: list[str] = []

    required_domains = {
        "analysis_session",
        "normalized_events",
        "run_context",
        "policy_and_instruction_context",
        "expected_vs_actual_delta",
        "extraction_quality_summary",
    }
    missing = sorted(domain for domain in required_domains if domain not in canonical_analysis)
    integrity_flags.extend(f"missing_domain:{domain}" for domain in missing)

    analysis_session = canonical_analysis.get("analysis_session") or {}
    if not analysis_session.get("source_provenance"):
        integrity_flags.append("missing_source_provenance")

    normalized_events = canonical_analysis.get("normalized_events") or []
    if not normalized_events:
        integrity_flags.append("no_normalized_events")

    quality = canonical_analysis.get("extraction_quality_summary") or {}
    if quality.get("overall_quality_band") == "insufficient_for_matching":
        quality_flags.append("insufficient_for_matching")
    if not quality.get("ordering_confidence") and normalized_events:
        quality_flags.append("missing_ordering_confidence")
    if quality.get("critical_gaps"):
        quality_flags.extend(f"critical_gap:{gap}" for gap in quality.get("critical_gaps", []))

    return sorted(set(integrity_flags)), sorted(set(quality_flags))


def _extract_features(canonical_analysis: dict[str, Any], result: AnalysisResult) -> dict[str, Any]:
    normalized_events = list(canonical_analysis.get("normalized_events") or [])
    delta = canonical_analysis.get("expected_vs_actual_delta") or {}
    instruction_context = canonical_analysis.get("policy_and_instruction_context") or {}
    quality = canonical_analysis.get("extraction_quality_summary") or {}

    tool_calls = [event for event in normalized_events if event.get("event_family") == "tool_call"]
    tool_results = [event for event in normalized_events if event.get("event_family") == "tool_result"]
    retrieval_queries = [event for event in normalized_events if event.get("event_family") == "retrieval_query"]
    retrieval_results = [event for event in normalized_events if event.get("event_family") == "retrieval_result"]
    state_reads = [event for event in normalized_events if event.get("event_family") == "state_read"]
    state_writes = [event for event in normalized_events if event.get("event_family") == "state_write"]
    confirmations = [event for event in normalized_events if event.get("event_family") == "confirmation_checkpoint"]
    model_decisions = [
        event for event in normalized_events if event.get("event_family") == "model_reasoning_or_decision"
    ]

    destructive_action_events = [
        event
        for event in tool_calls + state_writes
        if _has_safety_flag(event, "mutates_state") or _has_safety_flag(event, "executes_shell")
    ]
    failed_tool_events = [
        event for event in tool_results if _tool_result_status(event) == "error" or _failure_error(event)
    ]
    state_conflicts = [
        event
        for event in state_writes + tool_results
        if bool(((event.get("structured_payload") or {}).get("state_transition") or {}).get("state_conflict_flag"))
    ]

    tool_categories: dict[str, int] = {}
    for event in tool_calls + tool_results:
        category = ((event.get("structured_payload") or {}).get("tool_category") or "unknown")
        tool_categories[category] = tool_categories.get(category, 0) + 1

    delta_types = [item for item in delta.get("delta_types", []) if isinstance(item, str)]
    schema_requirement_present = any(
        constraint
        for key in ("system_constraints", "developer_constraints", "user_constraints")
        for constraint in instruction_context.get(key, [])
        if isinstance(constraint, dict)
        and isinstance(constraint.get("constraint"), str)
        and any(token in constraint["constraint"].lower() for token in ("schema", "json", "format", "exactly"))
    ) or "schema_or_contract_mismatch" in delta_types

    confirmation_before_action = _confirmation_before_action(confirmations, destructive_action_events)
    safeguard_requirement_present = _safeguard_requirement_present(instruction_context)
    safeguard_present = safeguard_requirement_present or bool(confirmations)
    retrieval_required = "retrieval_failure_or_omission" in delta_types

    return {
        "workflow_length": len(normalized_events),
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "tool_category_counts": tool_categories,
        "decision_count": len(model_decisions),
        "decision_density": round(len(model_decisions) / len(normalized_events), 4) if normalized_events else 0.0,
        "retrieval_present": bool(retrieval_queries or retrieval_results),
        "retrieval_query_count": len(retrieval_queries),
        "retrieval_result_count": len(retrieval_results),
        "retrieval_required": retrieval_required,
        "retrieval_used_ignored": retrieval_required and not bool(retrieval_queries or retrieval_results),
        "schema_requirement_present": schema_requirement_present,
        "output_schema_violated": "schema_or_contract_mismatch" in delta_types,
        "confirmation_checkpoint_count": len(confirmations),
        "confirmation_before_action": confirmation_before_action,
        "safeguard_requirement_present": safeguard_requirement_present,
        "safeguard_present": safeguard_present,
        "safeguard_omitted": (
            bool(destructive_action_events)
            and safeguard_requirement_present
            and not confirmation_before_action
        ),
        "destructive_action_count": len(destructive_action_events),
        "state_read_count": len(state_reads),
        "state_write_count": len(state_writes),
        "state_conflict_count": len(state_conflicts),
        "state_written_lost_conflicted": bool(state_conflicts),
        "expected_vs_actual_delta_types": delta_types,
        "tool_attempted_failed": bool(failed_tool_events),
        "tool_failed_count": len(failed_tool_events),
        "tool_misused": "tool_misuse" in delta_types,
        "integrity_status": (canonical_analysis.get("analysis_session") or {}).get("integrity_status"),
        "overall_quality_band": quality.get("overall_quality_band"),
        "ambiguity_count": quality.get("ambiguity_count", 0),
        "risk_summary": result.risk_summary,
        "flagged_event_count": result.flagged_events,
    }


def _match_rules(
    extracted_features: dict[str, Any],
    canonical_analysis: dict[str, Any],
    result: AnalysisResult,
) -> list[dict[str, Any]]:
    delta_types = set(extracted_features.get("expected_vs_actual_delta_types", []))
    supporting_event_ids = [
        item
        for item in (canonical_analysis.get("expected_vs_actual_delta") or {}).get("supporting_event_ids", [])
        if isinstance(item, str)
    ]
    rules: list[dict[str, Any]] = []

    if "missing_required_action" in delta_types or extracted_features["risk_summary"].get("coverage_gap"):
        rules.append(_rule("R-COV-001", "coverage_gap", "delta_missing_required_action", supporting_event_ids, ["expected_vs_actual_delta_types", "risk_summary.coverage_gap"]))

    if extracted_features["safeguard_omitted"]:
        rules.append(
            _rule(
                "R-VER-001",
                "verification_failure",
                "destructive_action_without_confirmation",
                _event_ids_for_family(canonical_analysis, {"state_write", "tool_call"}),
                [
                    "destructive_action_count",
                    "confirmation_before_action",
                    "safeguard_requirement_present",
                    "safeguard_omitted",
                ],
            )
        )

    if "wrong_action" in delta_types or extracted_features["risk_summary"].get("policy_divergence"):
        rules.append(_rule("R-POL-001", "policy_divergence", "policy_divergence_detected", supporting_event_ids, ["expected_vs_actual_delta_types", "risk_summary.policy_divergence"]))

    if extracted_features["retrieval_used_ignored"]:
        rules.append(_rule("R-RET-001", "retrieval_omission", "retrieval_required_but_absent", supporting_event_ids, ["retrieval_required", "retrieval_present", "retrieval_used_ignored"]))

    if extracted_features["state_conflict_count"] > 0:
        rules.append(_rule("R-STA-001", "state_conflict", "state_conflict_detected", _event_ids_for_state_conflicts(canonical_analysis), ["state_conflict_count", "state_written_lost_conflicted"]))

    if extracted_features["tool_misused"] or "tool_misuse" in delta_types:
        rules.append(_rule("R-TOOL-001", "tool_misuse", "tool_contract_violation", supporting_event_ids, ["tool_misused", "expected_vs_actual_delta_types"]))

    if extracted_features["risk_summary"].get("assumption_mutation"):
        rules.append(_rule("R-ASM-001", "assumption_mutation", "assumption_mutation_detected", _supporting_risk_event_ids(result), ["risk_summary.assumption_mutation"]))

    return rules


def _match_sequences(canonical_analysis: dict[str, Any], extracted_features: dict[str, Any]) -> list[dict[str, Any]]:
    events = list(canonical_analysis.get("normalized_events") or [])
    patterns: list[dict[str, Any]] = []

    destructive_action = _first_event(events, {"state_write", "tool_call"}, require_mutation=True)
    confirmation = _last_event_before(events, "confirmation_checkpoint", destructive_action)
    if (
        destructive_action is not None
        and confirmation is None
        and extracted_features["safeguard_requirement_present"]
    ):
        patterns.append(
            {
                "sequence_id": "SEQ-VER-001",
                "signature_key": "verification_failure",
                "pattern": ["instruction_received", "safeguard_omitted", "destructive_action_taken"],
                "supporting_event_ids": [destructive_action.get("event_id")],
            }
        )

    if extracted_features["retrieval_used_ignored"]:
        output_event = _first_event(events, {"output_emission", "actual_outcome_marker"})
        patterns.append(
            {
                "sequence_id": "SEQ-RET-001",
                "signature_key": "retrieval_omission",
                "pattern": ["retrieval_required", "retrieval_absent", "answer_asserted_anyway"],
                "supporting_event_ids": [
                    event_id
                    for event_id in [output_event.get("event_id") if output_event else None]
                    if isinstance(event_id, str)
                ],
            }
        )

    state_read = _first_event(events, {"state_read"})
    conflict_event = _first_state_conflict_event(events)
    if state_read is not None and conflict_event is not None and not extracted_features["confirmation_checkpoint_count"]:
        patterns.append(
            {
                "sequence_id": "SEQ-STA-001",
                "signature_key": "state_conflict",
                "pattern": ["state_read", "conflicting_write", "no_confirmation_checkpoint"],
                "supporting_event_ids": [state_read.get("event_id"), conflict_event.get("event_id")],
            }
        )

    failed_tool = _first_failed_tool_result(events)
    if failed_tool is not None:
        later_tool = _later_event(events, failed_tool, {"tool_call", "tool_result"})
        output_event = _later_event(events, failed_tool, {"output_emission", "actual_outcome_marker"})
        if later_tool is None and output_event is not None:
            patterns.append(
                {
                    "sequence_id": "SEQ-TOOL-001",
                    "signature_key": "tool_misuse",
                    "pattern": ["tool_error", "retry_missing", "premature_completion"],
                    "supporting_event_ids": [failed_tool.get("event_id"), output_event.get("event_id")],
                }
            )

    return patterns


def _global_contradictions(extracted_features: dict[str, Any], canonical_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    contradictions: list[dict[str, Any]] = []
    if extracted_features["confirmation_before_action"]:
        contradictions.append(
            {
                "flag": "confirmation_present_before_destructive_action",
                "candidate_keys": ["verification_failure"],
                "feature_ref": "confirmation_before_action",
            }
        )
    if extracted_features["retrieval_present"]:
        contradictions.append(
            {
                "flag": "retrieval_present",
                "candidate_keys": ["retrieval_omission"],
                "feature_ref": "retrieval_present",
            }
        )
    if "schema_or_contract_mismatch" not in extracted_features.get("expected_vs_actual_delta_types", []):
        contradictions.append(
            {
                "flag": "no_schema_mismatch_detected",
                "candidate_keys": ["tool_misuse"],
                "feature_ref": "expected_vs_actual_delta_types",
            }
        )
    return contradictions


def _candidate_signatures(
    *,
    matched_rules: list[dict[str, Any]],
    matched_sequence_patterns: list[dict[str, Any]],
    extracted_features: dict[str, Any],
    global_contradictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for rule in matched_rules:
        key = rule["signature_key"]
        candidate = by_key.setdefault(
            key,
            {
                "signature_key": key,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "matched_rule_ids": [],
                "matched_sequence_ids": [],
                "triggered_feature_refs": [],
                "confidence_notes": [],
            },
        )
        candidate["matched_rule_ids"].append(rule["rule_id"])
        candidate["triggered_feature_refs"].extend(rule.get("triggered_feature_refs", []))
        candidate["supporting_evidence"].extend(
            {"event_id": event_id, "source": rule["rule_id"]}
            for event_id in rule.get("supporting_event_ids", [])
            if isinstance(event_id, str)
        )

    for pattern in matched_sequence_patterns:
        key = pattern["signature_key"]
        candidate = by_key.setdefault(
            key,
            {
                "signature_key": key,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "matched_rule_ids": [],
                "matched_sequence_ids": [],
                "triggered_feature_refs": [],
                "confidence_notes": [],
            },
        )
        candidate["matched_sequence_ids"].append(pattern["sequence_id"])
        candidate["supporting_evidence"].extend(
            {"event_id": event_id, "source": pattern["sequence_id"]}
            for event_id in pattern.get("supporting_event_ids", [])
            if isinstance(event_id, str)
        )

    for candidate in by_key.values():
        key = candidate["signature_key"]
        contradictions = [item for item in global_contradictions if key in item.get("candidate_keys", [])]
        candidate["contradicting_evidence"] = [
            {"feature_ref": item["feature_ref"], "flag": item["flag"]} for item in contradictions
        ]
        score = 0.35
        score += 0.18 * len(candidate["matched_rule_ids"])
        score += 0.12 * len(candidate["matched_sequence_ids"])
        score += 0.03 * min(len(candidate["supporting_evidence"]), 4)
        score -= 0.14 * len(candidate["contradicting_evidence"])
        if extracted_features.get("overall_quality_band") == "degraded":
            score -= 0.08
            candidate["confidence_notes"].append("quality_degraded")
        if extracted_features.get("ambiguity_count", 0):
            score -= min(0.02 * extracted_features["ambiguity_count"], 0.08)
            candidate["confidence_notes"].append("ambiguity_present")
        candidate["deterministic_score"] = round(max(min(score, 0.99), 0.05), 3)
        candidate["explanation_snippet"] = _candidate_explanation(candidate)

    ordered = sorted(
        by_key.values(),
        key=lambda item: (-item["deterministic_score"], item["signature_key"]),
    )
    for index, candidate in enumerate(ordered, start=1):
        candidate["candidate_rank"] = index
    return ordered


def _unresolved_ambiguity_flag(
    *,
    extracted_features: dict[str, Any],
    candidate_signatures: list[dict[str, Any]],
    canonical_analysis: dict[str, Any],
) -> bool:
    delta_types = set((canonical_analysis.get("expected_vs_actual_delta") or {}).get("delta_types", []))
    if "unresolved_ambiguity" in delta_types:
        return True
    if extracted_features.get("overall_quality_band") == "degraded":
        return True
    if len(candidate_signatures) >= 2 and candidate_signatures[0]["deterministic_score"] == candidate_signatures[1]["deterministic_score"]:
        return True
    return False


def _status(
    *,
    integrity_flags: list[str],
    quality_flags: list[str],
    candidate_signatures: list[dict[str, Any]],
) -> str:
    if integrity_flags or "insufficient_for_matching" in quality_flags:
        return "insufficient_evidence"
    if candidate_signatures:
        return "matched"
    return "unclassified"


def _summary_text(deterministic_match: dict[str, Any], primary: dict[str, Any] | None) -> str:
    status = deterministic_match.get("status")
    candidates = deterministic_match.get("candidate_signatures") or []
    if status == "insufficient_evidence":
        return "Deterministic matching found insufficient structured evidence for a reliable OSS-safe candidate set."
    if not candidates:
        return "No deterministic OSS-safe candidate was recognised for this run."
    if primary is None:
        return "Deterministic matching produced candidate signatures from local OSS-safe signals."
    return f"Matched {len(candidates)} deterministic candidate signature(s) from local OSS-safe signals; top candidate is {primary['signature_key']}."


def _rule(
    rule_id: str,
    signature_key: str,
    rationale: str,
    supporting_event_ids: list[str],
    triggered_feature_refs: list[str],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_version": RULESET_VERSION,
        "signature_key": signature_key,
        "rationale": rationale,
        "supporting_event_ids": sorted(set(supporting_event_ids)),
        "triggered_feature_refs": triggered_feature_refs,
    }


def _event_ids_for_family(canonical_analysis: dict[str, Any], families: set[str]) -> list[str]:
    return [
        event.get("event_id")
        for event in canonical_analysis.get("normalized_events", [])
        if event.get("event_family") in families and isinstance(event.get("event_id"), str)
    ]


def _event_ids_for_state_conflicts(canonical_analysis: dict[str, Any]) -> list[str]:
    event_ids: list[str] = []
    for event in canonical_analysis.get("normalized_events", []):
        transition = (event.get("structured_payload") or {}).get("state_transition") or {}
        if transition.get("state_conflict_flag") and isinstance(event.get("event_id"), str):
            event_ids.append(event["event_id"])
    return event_ids


def _supporting_risk_event_ids(result: AnalysisResult) -> list[str]:
    return [str(event.id) for event in result.events if event.risk_classification and event.risk_classification.assumption_mutation]


def _has_safety_flag(event: dict[str, Any], flag: str) -> bool:
    payload = event.get("structured_payload") or {}
    flags = payload.get("safety_relevant_flags") or []
    return flag in flags


def _tool_result_status(event: dict[str, Any]) -> str | None:
    payload = event.get("structured_payload") or {}
    return payload.get("result_status")


def _failure_error(event: dict[str, Any]) -> bool:
    payload = event.get("structured_payload") or {}
    failure = payload.get("failure_context") or {}
    return bool(failure.get("error") or payload.get("error_code"))


def _confirmation_before_action(confirmations: list[dict[str, Any]], actions: list[dict[str, Any]]) -> bool:
    if not confirmations or not actions:
        return False
    first_action_index = min(int(event.get("sequence_index", 0)) for event in actions)
    return any(int(item.get("sequence_index", 0)) < first_action_index for item in confirmations)


def _safeguard_requirement_present(instruction_context: dict[str, Any]) -> bool:
    safeguard_tokens = (
        "confirm",
        "confirmation",
        "approve",
        "approval",
        "ask first",
        "permission",
        "before destructive",
        "before risky",
        "before mutating",
    )
    for key in (
        "system_constraints",
        "developer_constraints",
        "user_constraints",
        "derived_operational_constraints",
    ):
        for constraint in instruction_context.get(key, []):
            if not isinstance(constraint, dict):
                continue
            value = constraint.get("constraint")
            if isinstance(value, str) and any(token in value.lower() for token in safeguard_tokens):
                return True
    return False


def _first_event(
    events: list[dict[str, Any]],
    families: set[str],
    *,
    require_mutation: bool = False,
) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_family") not in families:
            continue
        if require_mutation and not _has_safety_flag(event, "mutates_state") and not _has_safety_flag(event, "executes_shell"):
            continue
        return event
    return None


def _last_event_before(
    events: list[dict[str, Any]],
    family: str,
    anchor: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if anchor is None:
        return None
    anchor_index = int(anchor.get("sequence_index", 0))
    matches = [event for event in events if event.get("event_family") == family and int(event.get("sequence_index", 0)) < anchor_index]
    return matches[-1] if matches else None


def _first_state_conflict_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        transition = ((event.get("structured_payload") or {}).get("state_transition") or {})
        if transition.get("state_conflict_flag"):
            return event
    return None


def _first_failed_tool_result(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_family") != "tool_result":
            continue
        if _tool_result_status(event) == "error" or _failure_error(event):
            return event
    return None


def _later_event(
    events: list[dict[str, Any]],
    anchor: dict[str, Any],
    families: set[str],
) -> dict[str, Any] | None:
    anchor_index = int(anchor.get("sequence_index", 0))
    for event in events:
        if int(event.get("sequence_index", 0)) <= anchor_index:
            continue
        if event.get("event_family") in families:
            return event
    return None


def _candidate_explanation(candidate: dict[str, Any]) -> str:
    definition = _CANDIDATES.get(candidate["signature_key"])
    summary = definition.summary_template if definition else candidate["signature_key"]
    rule_count = len(candidate.get("matched_rule_ids", []))
    sequence_count = len(candidate.get("matched_sequence_ids", []))
    return f"{summary} Supported by {rule_count} rule(s) and {sequence_count} ordered sequence pattern(s)."
