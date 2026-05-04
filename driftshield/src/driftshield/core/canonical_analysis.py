"""Phase 3g canonical analysed-run builder."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.models import CanonicalEvent, EventType, Session as DomainSession

if TYPE_CHECKING:
    from driftshield.db.persistence import IngestProvenance

ANALYSIS_SCHEMA_VERSION = "phase-3g-canonical-v1"

_DIRECT_RECOVERY_MODE = "direct"
_NORMALISED_RECOVERY_MODE = "normalised"
_INFERRED_RECOVERY_MODE = "inferred"

_BASE_NORMALISED_FIELDS = {
    "actor_type",
    "confidence",
    "event_family",
    "event_type",
    "recovery_mode",
    "sequence_index",
}


def build_canonical_analysis(
    *,
    session: DomainSession,
    result: AnalysisResult,
    provenance: IngestProvenance | None,
) -> dict[str, Any]:
    normalized_events = _canonical_event_payloads(result.events)
    missing_fields = sum(len(event["missing_fields"]) for event in normalized_events)
    ambiguity_count = sum(len(event.ambiguities) for event in result.events)
    direct_events = sum(1 for event in normalized_events if event["recovery_mode"] == _DIRECT_RECOVERY_MODE)
    normalised_events = sum(
        1 for event in normalized_events if event["recovery_mode"] == _NORMALISED_RECOVERY_MODE
    )
    inferred_events = sum(
        1 for event in normalized_events if event["recovery_mode"] == _INFERRED_RECOVERY_MODE
    )
    recovered_fields = sum(_recovered_field_count(event["field_recovery"]) for event in normalized_events)
    inferred_fields = sum(
        len(event["field_recovery"]["inferred_fields"]) for event in normalized_events
    )

    integrity_reasons = _integrity_reasons(result.events)
    overall_quality_band = _overall_quality_band(result.events, ambiguity_count=ambiguity_count)
    delta_types = _delta_types(result)
    parser_name = _parser_name(provenance)
    coverage_ratio = round(_coverage_ratio(normalized_events), 4)
    ordering_confidence = _ordering_confidence(result.events)
    critical_gaps = _critical_gaps(result.events)
    quality_warnings = _quality_warnings(result.events)

    return {
        "analysis_session": {
            "session_id": str(session.id),
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "source_kind": parser_name,
            "source_provenance": {
                "source_type": parser_name,
                "source_session_id": provenance.source_session_id if provenance else session.external_id,
                "source_path": provenance.source_path if provenance else None,
            },
            "parser_name": parser_name,
            "parser_version": provenance.parser_version if provenance else None,
            "ingested_at": provenance.ingested_at.isoformat() if provenance else None,
            "source_fingerprint": provenance.transcript_hash if provenance else None,
            "time_bounds": _time_bounds(result.events),
            "event_count": len(normalized_events),
            "integrity_status": _integrity_status(result.events),
            "integrity_reasons": integrity_reasons,
        },
        "normalized_events": normalized_events,
        "run_context": {
            "workflow_label": session.metadata.get("workflow_label") if isinstance(session.metadata, dict) else None,
            "environment": session.metadata.get("environment") if isinstance(session.metadata, dict) else None,
            "repository_or_workspace": provenance.source_path if provenance else None,
            "tool_availability_summary": _tool_availability_summary(result.events),
            "major_constraints": _major_constraints(result.events),
            "user_goal_summary": _user_goal_summary(result.events),
        },
        "policy_and_instruction_context": {
            "system_constraints": _constraints_for_role(result.events, "system"),
            "developer_constraints": _developer_constraints(result.events),
            "user_constraints": _constraints_for_role(result.events, "user"),
            "derived_operational_constraints": _derived_operational_constraints(result.events),
            "conflict_or_shadowing_notes": _constraint_conflicts(result.events),
        },
        "expected_vs_actual_delta": {
            "delta_present": bool(delta_types),
            "expected_outcome_summary": _expected_outcome_summary(result.events),
            "actual_outcome_summary": _actual_outcome_summary(result.events),
            "delta_types": delta_types or ["no_material_delta_detected"],
            "severity_hint": _severity_hint(result),
            "supporting_event_ids": _supporting_event_ids(result),
            "blocked_goal_summary": _blocked_goal_summary(result),
        },
        "extraction_quality_summary": {
            "overall_quality_band": overall_quality_band,
            "coverage_ratio": coverage_ratio,
            "parse_completeness": coverage_ratio,
            "missing_event_families": _missing_event_families(normalized_events),
            "ordering_confidence": ordering_confidence,
            "structural_confidence": _structural_confidence(
                coverage_ratio=coverage_ratio,
                ordering_confidence=ordering_confidence,
                ambiguity_count=ambiguity_count,
            ),
            "ambiguity_count": ambiguity_count,
            "field_recovery_summary": {
                "direct_event_count": direct_events,
                "normalised_event_count": normalised_events,
                "inferred_event_count": inferred_events,
                "missing_field_count": missing_fields,
                "recovered_field_count": recovered_fields,
                "inferred_field_count": inferred_fields,
            },
            "inference_ratio": round(inferred_events / len(normalized_events), 4) if normalized_events else 0.0,
            "critical_gaps": critical_gaps,
            "missing_critical_fields_status": _missing_critical_fields_status(critical_gaps),
            "parser_warnings": _parser_warnings(result.events),
            "quality_warnings": quality_warnings,
            "review_requirements": _review_requirements(
                critical_gaps=critical_gaps,
                quality_warnings=quality_warnings,
                ambiguity_count=ambiguity_count,
                overall_quality_band=overall_quality_band,
            ),
        },
    }


def _canonical_event_payloads(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    sequence_index = 0
    for event in events:
        payloads.append(_canonical_event_payload(event, sequence_index=sequence_index))
        sequence_index += 1
        if _has_result_payload(event):
            payloads.append(_canonical_result_payload(event, sequence_index=sequence_index))
            sequence_index += 1
    return payloads


def _canonical_event_payload(
    event: CanonicalEvent,
    *,
    sequence_index: int,
    event_id: str | None = None,
    event_family: str | None = None,
    content_summary: str | None = None,
    causal_parents: list[str] | None = None,
    structured_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_reference = next((ref for ref in event.source_refs if ref.get("kind") != "parser"), None)
    source_span = None
    if raw_reference is not None:
        source_span = {
            "kind": raw_reference.get("kind"),
            "value": raw_reference.get("value"),
        }

    payload = structured_payload or _structured_payload(event, raw_reference=raw_reference)
    missing_fields = _event_missing_fields(event)
    recovery_mode = _recovery_mode(event, missing_fields=missing_fields)
    field_recovery = _field_recovery(
        event,
        raw_reference=raw_reference,
        payload=payload,
        missing_fields=missing_fields,
        recovery_mode=recovery_mode,
        content_summary=content_summary,
        causal_parents=causal_parents,
    )

    return {
        "event_id": event_id or str(event.id),
        "sequence_index": sequence_index,
        "event_family": event_family or _event_family(event),
        "event_type": event.event_kind,
        "actor_type": (event.actor or {}).get("role") or "assistant",
        "timestamp": event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else None,
        "source_span": source_span,
        "raw_reference": raw_reference,
        "content_summary": content_summary or event.summary,
        "structured_payload": payload,
        "causal_parents": causal_parents if causal_parents is not None else [str(ref) for ref in event.parent_event_refs],
        "confidence": _event_confidence(event, missing_fields=missing_fields),
        "recovery_mode": recovery_mode,
        "field_recovery": field_recovery,
        "missing_fields": missing_fields,
    }


def _structured_payload(
    event: CanonicalEvent,
    *,
    raw_reference: dict[str, str] | None,
) -> dict[str, Any]:
    structured_payload: dict[str, Any] = {
        "action": event.action,
        "inputs": event.inputs,
        "outputs": event.outputs,
    }
    if event.constraints:
        structured_payload["constraints"] = [dict(item) for item in event.constraints]
    if event.tool_activity:
        structured_payload["tool_activity"] = dict(event.tool_activity)
        structured_payload.update(_tool_payload(event, raw_reference=raw_reference))
    state_transition = _state_transition_payload(event)
    if state_transition is not None:
        structured_payload["state_transition"] = state_transition
    if event.failure_context:
        structured_payload["failure_context"] = dict(event.failure_context)
    if event.artifact_refs:
        structured_payload["artifact_refs"] = [dict(item) for item in event.artifact_refs]
    return structured_payload


def _canonical_result_payload(event: CanonicalEvent, *, sequence_index: int) -> dict[str, Any]:
    result_payload = {
        "action": event.action,
        "outputs": event.outputs,
        "tool_activity": dict(event.tool_activity or {}),
        **_tool_payload(event, raw_reference=_tool_raw_reference(event)),
    }
    if event.failure_context:
        result_payload["failure_context"] = dict(event.failure_context)
    if event.artifact_refs:
        result_payload["artifact_refs"] = [dict(item) for item in event.artifact_refs]

    return _canonical_event_payload(
        event,
        sequence_index=sequence_index,
        event_id=f"{event.id}:result",
        event_family=_result_event_family(event),
        content_summary=_tool_result_summary(event),
        causal_parents=[str(event.id)],
        structured_payload=result_payload,
    )


def _event_family(event: CanonicalEvent) -> str:
    actor_role = (event.actor or {}).get("role")
    if actor_role == "user":
        return "user_instruction"
    if actor_role == "system":
        if event.constraints:
            return "policy_instruction"
        return "system_instruction"
    if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF}:
        return _tool_event_family(event)
    if event.failure_context:
        return "error_or_exception"
    if event.event_type == EventType.OUTPUT:
        if event.constraints:
            return "actual_outcome_marker"
        return "output_emission"
    if event.event_type == EventType.CONSTRAINT_CHECK:
        return "confirmation_checkpoint"
    if event.constraints:
        return "expectation_marker"
    return "model_reasoning_or_decision"


def _event_missing_fields(event: CanonicalEvent) -> list[str]:
    missing: list[str] = []
    if not event.source_refs:
        missing.append("source_reference_missing")
    if not event.summary:
        missing.append("content_summary_missing")
    if not event.parent_event_refs and (event.ordinal or 0) > 0:
        missing.append("causal_parents_missing")
    if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF} and not event.inputs:
        missing.append("tool_inputs_missing")
    if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF} and not event.outputs:
        missing.append("tool_outputs_missing")
    return sorted(set(missing + list(event.ambiguities)))


def _recovery_mode(event: CanonicalEvent, *, missing_fields: list[str]) -> str:
    if event.ambiguities or any(item.endswith("_inferred_from_text") for item in missing_fields):
        return _INFERRED_RECOVERY_MODE
    if missing_fields:
        return _NORMALISED_RECOVERY_MODE
    return _DIRECT_RECOVERY_MODE


def _event_confidence(event: CanonicalEvent, *, missing_fields: list[str]) -> float:
    confidence = 1.0
    confidence -= min(0.15 * len(missing_fields), 0.45)
    if event.failure_context and event.failure_context.get("status") == "warning":
        confidence -= 0.1
    return round(max(confidence, 0.2), 2)


def _field_recovery(
    event: CanonicalEvent,
    *,
    raw_reference: dict[str, str] | None,
    payload: dict[str, Any],
    missing_fields: list[str],
    recovery_mode: str,
    content_summary: str | None,
    causal_parents: list[str] | None,
) -> dict[str, list[str]]:
    direct_fields: set[str] = set()
    normalised_fields = set(_BASE_NORMALISED_FIELDS)
    inferred_fields: set[str] = set()

    if event.timestamp is not None:
        direct_fields.add("timestamp")
    if raw_reference is not None:
        direct_fields.update({"raw_reference", "source_span"})
    if content_summary is not None or event.summary:
        direct_fields.add("content_summary")
    if event.parent_event_refs or causal_parents:
        direct_fields.add("causal_parents")

    if event.ambiguities:
        inferred_fields.update(_inferred_fields_from_ambiguities(event.ambiguities))

    if event.failure_context and event.failure_context.get("status") == "warning":
        inferred_fields.update({"structured_payload.failure_context", "structured_payload.tool_activity"})

    if recovery_mode == _NORMALISED_RECOVERY_MODE:
        normalised_fields.update(_normalised_fields_from_missing_fields(missing_fields))
    if recovery_mode == _INFERRED_RECOVERY_MODE:
        normalised_fields.update(_normalised_fields_from_missing_fields(missing_fields))

    if payload and not _has_non_direct_structured_payload_fields(
        normalised_fields=normalised_fields,
        inferred_fields=inferred_fields,
    ):
        direct_fields.add("structured_payload")

    direct_fields -= inferred_fields

    return {
        "direct_fields": sorted(direct_fields),
        "normalised_fields": sorted(normalised_fields),
        "inferred_fields": sorted(inferred_fields),
        "missing_fields": list(missing_fields),
    }


def _recovered_field_count(field_recovery: dict[str, list[str]]) -> int:
    return len(set(field_recovery["normalised_fields"]) - _BASE_NORMALISED_FIELDS)


def _has_non_direct_structured_payload_fields(
    *,
    normalised_fields: set[str],
    inferred_fields: set[str],
) -> bool:
    return any(field.startswith("structured_payload.") for field in normalised_fields | inferred_fields)


def _normalised_fields_from_missing_fields(missing_fields: list[str]) -> set[str]:
    field_map = {
        "causal_parents_missing": "causal_parents",
        "content_summary_missing": "content_summary",
        "source_reference_missing": "raw_reference",
        "tool_inputs_missing": "structured_payload.inputs",
        "tool_outputs_missing": "structured_payload.outputs",
    }
    return {field_map[item] for item in missing_fields if item in field_map}


def _inferred_fields_from_ambiguities(ambiguities: list[str]) -> set[str]:
    field_map = {
        "failure_inferred_from_text": "structured_payload.failure_context",
        "missing_actor": "actor_type",
        "missing_parent_ref": "causal_parents",
        "missing_source_ref": "raw_reference",
        "missing_tool_inputs": "structured_payload.inputs",
        "missing_tool_outputs": "structured_payload.outputs",
    }
    inferred_fields = {field_map[item] for item in ambiguities if item in field_map}
    if "failure_inferred_from_text" in ambiguities:
        inferred_fields.add("recovery_mode")
    return inferred_fields


def _has_result_payload(event: CanonicalEvent) -> bool:
    return bool(event.tool_activity and (event.outputs or event.failure_context))


def _tool_raw_reference(event: CanonicalEvent) -> dict[str, str] | None:
    return next((ref for ref in event.source_refs if ref.get("kind") != "parser"), None)


def _tool_event_family(event: CanonicalEvent) -> str:
    tool_name = str((event.tool_activity or {}).get("name") or event.action or "").lower()
    category = str((event.tool_activity or {}).get("category") or "").lower()

    if tool_name in {"read", "read_file", "cat"} or "file_io" in category and "read" in tool_name:
        return "state_read"
    if tool_name in {"write", "edit", "apply_patch"} or "file_io" in category and tool_name in {"write", "edit"}:
        return "state_write"
    if tool_name in {"grep", "glob", "search", "web_search", "web_fetch"} or "search" in tool_name:
        return "retrieval_query"
    if event.failure_context:
        return "error_or_exception"
    return "tool_call"



def _result_event_family(event: CanonicalEvent) -> str:
    return "retrieval_result" if _tool_event_family(event) == "retrieval_query" else "tool_result"


def _tool_result_summary(event: CanonicalEvent) -> str:
    tool_name = str((event.tool_activity or {}).get("name") or event.action or "tool")
    if event.failure_context and event.failure_context.get("error"):
        return f"{tool_name} returned an error"
    result_summary = _mapping_summary(event.outputs)
    if result_summary:
        return f"{tool_name} returned {result_summary}"
    return f"{tool_name} returned a result"


def _tool_payload(event: CanonicalEvent, *, raw_reference: dict[str, str] | None) -> dict[str, Any]:
    tool_activity = event.tool_activity or {}
    artifact_target = next((ref.get("value") for ref in event.artifact_refs if ref.get("value")), None)
    invocation_id = None
    if raw_reference is not None and raw_reference.get("kind") in {"tool_use_id", "tool_call_id"}:
        invocation_id = raw_reference.get("value")

    payload: dict[str, Any] = {
        "tool_name": tool_activity.get("name") or event.action,
        "tool_category": tool_activity.get("category"),
        "arguments_summary": _mapping_summary(event.inputs),
        "target_summary": artifact_target,
        "invocation_id": invocation_id,
        "safety_relevant_flags": _tool_safety_flags(event),
        "result_status": tool_activity.get("status"),
        "result_summary": _mapping_summary(event.outputs),
        "result_artifact_refs": [dict(item) for item in event.artifact_refs],
        "error_code": (event.outputs or {}).get("error") or (event.failure_context or {}).get("error"),
    }
    return payload



def _state_transition_payload(event: CanonicalEvent) -> dict[str, Any] | None:
    family = _tool_event_family(event) if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF} else None
    if family not in {"state_read", "state_write"}:
        return None

    subject = next((ref.get("value") for ref in event.artifact_refs if ref.get("value")), None)
    operation = "read" if family == "state_read" else "write"
    if str(event.action).lower() == "edit":
        operation = "update"
    elif str(event.action).lower() == "apply_patch":
        operation = "patch"

    return {
        "state_subject": subject,
        "prior_state_summary": None,
        "proposed_state_summary": _mapping_summary(event.inputs) if family == "state_write" else None,
        "applied_state_summary": _mapping_summary(event.outputs),
        "state_operation": operation,
        "state_conflict_flag": bool(event.failure_context),
        "state_conflict_reason": (event.failure_context or {}).get("error"),
    }



def _parser_name(provenance: IngestProvenance | None) -> str | None:
    if provenance is None:
        return None
    return provenance.parser_version.split("@", 1)[0]


def _time_bounds(events: list[CanonicalEvent]) -> dict[str, str | None]:
    if not events:
        return {"started_at": None, "ended_at": None}
    return {
        "started_at": events[0].timestamp.isoformat(),
        "ended_at": events[-1].timestamp.isoformat(),
    }


def _integrity_status(events: list[CanonicalEvent]) -> str:
    if not events:
        return "corrupted_but_usable"
    if any(event.failure_context for event in events):
        return "recovered"
    if any(event.ambiguities for event in events):
        return "partial"
    return "complete"


def _integrity_reasons(events: list[CanonicalEvent]) -> list[str]:
    reasons: set[str] = set()
    for event in events:
        reasons.update(event.ambiguities)
        if event.failure_context:
            reasons.add("failure_context_present")
        if not event.source_refs:
            reasons.add("missing_source_reference")
    return sorted(reasons)


def _mapping_summary(payload: object) -> str | None:
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())
        return ", ".join(keys[:6]) if keys else None
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if payload is None:
        return None
    return str(payload)[:160]



def _tool_safety_flags(event: CanonicalEvent) -> list[str]:
    flags: list[str] = []
    tool_name = str((event.tool_activity or {}).get("name") or event.action or "").lower()
    if tool_name in {"bash", "shell"}:
        flags.append("executes_shell")
    if tool_name in {"write", "edit", "apply_patch"}:
        flags.append("mutates_state")
    if event.failure_context:
        flags.append("reported_failure")
    return flags



def _tool_availability_summary(events: list[CanonicalEvent]) -> dict[str, Any]:
    tool_names = sorted(
        {
            str((event.tool_activity or {}).get("name"))
            for event in events
            if event.tool_activity and (event.tool_activity or {}).get("name")
        }
    )
    return {
        "tool_count": len(tool_names),
        "tool_names": tool_names,
    }


def _major_constraints(events: list[CanonicalEvent]) -> list[str]:
    values: list[str] = []
    for event in events:
        for constraint in event.constraints:
            value = constraint.get("value")
            if isinstance(value, str) and value not in values:
                values.append(value)
    return values[:10]


def _user_goal_summary(events: list[CanonicalEvent]) -> str | None:
    for event in events:
        if (event.actor or {}).get("role") == "user" and event.summary:
            return event.summary
    return None


def _constraints_for_role(events: list[CanonicalEvent], role: str) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for event in events:
        if (event.actor or {}).get("role") != role:
            continue
        for constraint in event.constraints:
            payload.append(
                {
                    "constraint": constraint.get("value"),
                    "source": constraint.get("source"),
                    "observed_via": "direct",
                    "event_id": str(event.id),
                }
            )
    return payload


def _developer_constraints(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    payload = _constraints_for_role(events, "developer")
    for event in events:
        if not event.constraints or not _looks_like_developer_instruction_source(event):
            continue
        for constraint in event.constraints:
            payload.append(
                {
                    "constraint": constraint.get("value"),
                    "source": constraint.get("source"),
                    "observed_via": "inferred_from_instruction_artifact",
                    "event_id": str(event.id),
                }
            )
    return payload


def _looks_like_developer_instruction_source(event: CanonicalEvent) -> bool:
    instruction_markers = (
        "soul.md",
        "style.md",
        "identity.md",
        "voice.md",
        "agents.md",
        "prompt",
        "persona",
        ".claude",
        ".openclaw",
    )
    values: list[str] = []
    values.extend(str(ref.get("value", "")).lower() for ref in event.artifact_refs)
    values.extend(str(ref.get("value", "")).lower() for ref in event.source_refs)
    return any(marker in value for value in values for marker in instruction_markers)


def _derived_operational_constraints(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for event in events:
        for constraint in event.constraints:
            payload.append(
                {
                    "constraint": constraint.get("value"),
                    "kind": constraint.get("kind"),
                    "event_id": str(event.id),
                    "observed_via": "normalised",
                }
            )
    return payload


def _constraint_conflicts(events: list[CanonicalEvent]) -> list[str]:
    role_counts: dict[str, int] = {}
    for event in events:
        role = (event.actor or {}).get("role") or "assistant"
        if event.constraints:
            role_counts[role] = role_counts.get(role, 0) + len(event.constraints)
    if sum(role_counts.values()) > 1 and len(role_counts) > 1:
        return ["multi_source_constraints_present"]
    return []


def _expected_outcome_summary(events: list[CanonicalEvent]) -> str | None:
    for event in events:
        for constraint in event.constraints:
            if constraint.get("kind") == "expected_output":
                return str(constraint.get("value"))
    return _user_goal_summary(events)


def _actual_outcome_summary(events: list[CanonicalEvent]) -> str | None:
    for event in reversed(events):
        if event.summary:
            return event.summary
    return None


def _delta_types(result: AnalysisResult) -> list[str]:
    delta_types: list[str] = []
    summary = result.risk_summary
    if summary.get("coverage_gap"):
        delta_types.append("missing_required_action")
    if summary.get("constraint_violation"):
        delta_types.append("policy_violation")
    if summary.get("context_contamination"):
        delta_types.append("retrieval_failure_or_omission")
    if summary.get("policy_divergence"):
        delta_types.append("wrong_action")
    if result.candidate_break_point and not result.candidate_break_point.is_identified and result.flagged_events:
        delta_types.append("unresolved_ambiguity")
    return sorted(set(delta_types))


def _severity_hint(result: AnalysisResult) -> str:
    if result.flagged_events >= 3:
        return "high"
    if result.flagged_events >= 1:
        return "medium"
    return "low"


def _supporting_event_ids(result: AnalysisResult) -> list[str]:
    return [str(event.id) for event in result.events if event.has_risk_flags()]


def _blocked_goal_summary(result: AnalysisResult) -> str | None:
    if not result.flagged_events:
        return None
    if result.candidate_break_point is not None:
        return result.candidate_break_point.summary
    return "Run deviated from the expected outcome."


def _coverage_ratio(normalized_events: list[dict[str, Any]]) -> float:
    if not normalized_events:
        return 0.0
    total_fields = len(normalized_events) * 10
    missing = sum(len(event["missing_fields"]) for event in normalized_events)
    return max(0.0, min(1.0, (total_fields - missing) / total_fields))


def _structural_confidence(
    *,
    coverage_ratio: float,
    ordering_confidence: float,
    ambiguity_count: int,
) -> float:
    confidence = min(coverage_ratio, ordering_confidence)
    confidence -= min(ambiguity_count * 0.03, 0.3)
    return round(max(confidence, 0.0), 4)


def _missing_event_families(normalized_events: list[dict[str, Any]]) -> list[str]:
    required = {
        "user_instruction",
        "system_instruction",
        "policy_instruction",
        "model_reasoning_or_decision",
        "tool_call",
        "tool_result",
        "retrieval_query",
        "retrieval_result",
        "state_read",
        "state_write",
        "confirmation_checkpoint",
        "output_emission",
        "error_or_exception",
        "expectation_marker",
        "actual_outcome_marker",
    }
    present = {str(event["event_family"]) for event in normalized_events}
    return sorted(required - present)


def _ordering_confidence(events: list[CanonicalEvent]) -> float:
    if not events:
        return 0.0
    ambiguity_penalty = sum(1 for event in events if "missing_parent_ref" in event.ambiguities)
    confidence = 1.0 - min(ambiguity_penalty * 0.1, 0.5)
    return round(max(confidence, 0.4), 2)


def _critical_gaps(events: list[CanonicalEvent]) -> list[str]:
    gaps: set[str] = set()
    for event in events:
        if not event.source_refs:
            gaps.add("missing_source_reference")
        if event.event_type in {EventType.TOOL_CALL, EventType.HANDOFF} and not event.outputs:
            gaps.add("missing_tool_result")
    return sorted(gaps)


def _quality_warnings(events: list[CanonicalEvent]) -> list[str]:
    warnings: set[str] = set()
    for event in events:
        if event.failure_context and event.failure_context.get("status") == "warning":
            warnings.add("failure_only_inferred_from_text")
        if event.ambiguities:
            warnings.add("event_ambiguities_present")
    return sorted(warnings)


def _parser_warnings(events: list[CanonicalEvent]) -> list[str]:
    warnings: set[str] = set()
    for event in events:
        if not event.source_refs:
            warnings.add("missing_source_reference")
        if event.failure_context and event.failure_context.get("status") == "warning":
            warnings.add("parser_recovered_from_text_only_failure")
        if event.ambiguities:
            warnings.add("parser_observed_ambiguous_event_fields")
    return sorted(warnings)


def _missing_critical_fields_status(critical_gaps: list[str]) -> str:
    if not critical_gaps:
        return "complete"
    if len(critical_gaps) >= 2:
        return "missing"
    return "partial"


def _review_requirements(
    *,
    critical_gaps: list[str],
    quality_warnings: list[str],
    ambiguity_count: int,
    overall_quality_band: str,
) -> list[str]:
    requirements: list[str] = []
    if critical_gaps:
        requirements.append("manual_review_required_for_missing_critical_fields")
    if ambiguity_count:
        requirements.append("manual_review_required_for_ambiguous_lineage")
    if quality_warnings:
        requirements.append("manual_review_required_for_parser_warnings")
    if overall_quality_band in {"degraded", "insufficient_for_matching"}:
        requirements.append("manual_review_required_before_matching")
    return requirements


def _overall_quality_band(events: list[CanonicalEvent], *, ambiguity_count: int) -> str:
    if not events:
        return "insufficient_for_matching"
    if ambiguity_count >= max(3, len(events)):
        return "degraded"
    if any(not event.source_refs for event in events):
        return "usable"
    return "high"
