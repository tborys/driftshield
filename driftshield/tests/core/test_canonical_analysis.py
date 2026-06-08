from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.analysis.session import AnalysisResult, analyze_session
from driftshield.core.canonical_analysis import build_canonical_analysis
from driftshield.core.deterministic_matching import build_deterministic_match
from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    RiskClassification,
    Session,
    SessionStatus,
)
from driftshield.core.normalization import normalize_events
from driftshield.core.visibility import (
    KNOWN_CLASSIFIABILITY_INPUTS_FIELDS,
    KNOWN_DELTA_RECORD_FIELDS,
    KNOWN_PROVENANCE_ENV_FIELDS,
    KNOWN_QUALIFICATION_FIELDS,
    apply_visibility,
)
from driftshield.db.persistence import IngestProvenance
from driftshield.parsers.claude_code import ClaudeCodeParser


def _completed_session(metadata=None, external_id=None):
    return Session(
        id=uuid4(),
        agent_id="claude",
        started_at=datetime.now(timezone.utc),
        external_id=external_id,
        status=SessionStatus.COMPLETED,
        metadata=metadata or {},
    )


def _provenance(source_path=None):
    return IngestProvenance(
        transcript_hash="hash-1",
        source_session_id="src-1",
        source_path=source_path,
        parser_version="claude_code@1",
        ingested_at=datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_build_canonical_analysis_emits_result_families_for_completed_tool_calls():
    transcript = "\n".join(
        [
            '{"sessionId":"canonical-1","type":"assistant","timestamp":"2026-05-04T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tool_1","name":"Read","input":{"file_path":"README.md"}}]}}',
            '{"sessionId":"canonical-1","type":"user","timestamp":"2026-05-04T12:00:01Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool_1","content":"file contents here","is_error":false}]}}',
        ]
    )
    events = ClaudeCodeParser().parse(transcript)
    result = analyze_session(events)

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    families = [event["event_family"] for event in payload["normalized_events"]]
    assert "state_read" in families
    assert "tool_result" in families
    assert "tool_result" not in payload["extraction_quality_summary"]["missing_event_families"]

    result_event = next(
        event for event in payload["normalized_events"] if event["event_family"] == "tool_result"
    )
    assert result_event["causal_parents"] == [payload["normalized_events"][0]["event_id"]]
    assert result_event["structured_payload"]["invocation_id"] == "tool_1"
    assert result_event["structured_payload"]["result_status"] == "completed"
    assert payload["extraction_quality_summary"]["field_recovery_summary"]["recovered_field_count"] == 0


def test_build_canonical_analysis_preserves_developer_constraints_from_instruction_artifacts():
    event = CanonicalEvent(
        id=uuid4(),
        session_id="canonical-2",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action="Read",
        inputs={"file_path": "/tmp/.openclaw/SOUL.md"},
        outputs={"result": "You must verify changes before replying."},
        metadata={"tool_use_id": "tool_2", "semantic_action_category": "file_io"},
    )
    events = normalize_events([event], source_type="claude_code")
    result = analyze_session(events)

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    developer_constraints = payload["policy_and_instruction_context"]["developer_constraints"]
    assert developer_constraints
    assert developer_constraints[0]["constraint"] == "You must verify changes before replying."
    assert developer_constraints[0]["observed_via"] == "inferred_from_instruction_artifact"


def test_build_canonical_analysis_exposes_extraction_quality_contract_for_ambiguous_runs():
    event = CanonicalEvent(
        id=uuid4(),
        session_id="canonical-3",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action="Read",
        inputs={"file_path": "README.md"},
        outputs={},
        ambiguities=["missing_parent_ref"],
    )
    result = analyze_session([event])

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    quality = payload["extraction_quality_summary"]
    assert quality["parse_completeness"] == quality["coverage_ratio"]
    assert quality["ambiguity_count"] >= 1
    assert quality["structural_confidence"] < 1.0
    assert quality["missing_critical_fields_status"] == "missing"
    assert "parser_observed_ambiguous_event_fields" in quality["parser_warnings"]
    assert "manual_review_required_for_missing_critical_fields" in quality["review_requirements"]
    assert "manual_review_required_for_ambiguous_lineage" in quality["review_requirements"]


def test_build_canonical_analysis_does_not_treat_missing_fields_as_ambiguity():
    event = CanonicalEvent(
        id=uuid4(),
        session_id="canonical-4",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action="Read",
        inputs={"file_path": "README.md"},
        outputs={},
        summary="Read invoked on README.md",
        source_refs=[{"kind": "message_id", "value": "tool-call-1"}],
    )
    result = AnalysisResult(
        events=[event],
        graph=LineageGraph(session_id=event.session_id),
        inflection_node=None,
        total_events=1,
        flagged_events=0,
    )

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    quality = payload["extraction_quality_summary"]
    event_payload = payload["normalized_events"][0]

    assert event_payload["recovery_mode"] == "normalised"
    assert event_payload["field_recovery"]["normalised_fields"]
    assert "structured_payload.outputs" in event_payload["field_recovery"]["normalised_fields"]
    assert "structured_payload" not in event_payload["field_recovery"]["direct_fields"]
    assert event_payload["field_recovery"]["inferred_fields"] == []
    assert quality["field_recovery_summary"]["missing_field_count"] >= 1
    assert quality["field_recovery_summary"]["normalised_event_count"] == 1
    assert quality["field_recovery_summary"]["inferred_event_count"] == 0
    assert quality["ambiguity_count"] == 0
    assert "manual_review_required_for_ambiguous_lineage" not in quality["review_requirements"]


def test_build_canonical_analysis_exposes_field_recovery_provenance_for_inferred_failures():
    event = CanonicalEvent(
        id=uuid4(),
        session_id="canonical-5",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action="Read",
        inputs={"file_path": "README.md"},
        outputs={"result": "permission denied while reading README.md"},
        source_refs=[{"kind": "message_id", "value": "tool-call-2"}],
        artifact_refs=[{"kind": "file_path", "value": "README.md"}],
        failure_context={
            "status": "warning",
            "error": None,
            "signals": ["failure_language"],
            "declared_failure": True,
        },
        ambiguities=["failure_inferred_from_text"],
        summary="Read reported a warning on README.md",
    )
    result = AnalysisResult(
        events=[event],
        graph=LineageGraph(session_id=event.session_id),
        inflection_node=None,
        total_events=1,
        flagged_events=0,
    )

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    event_payload = payload["normalized_events"][0]
    quality = payload["extraction_quality_summary"]

    assert event_payload["recovery_mode"] == "inferred"
    assert "structured_payload" not in event_payload["field_recovery"]["direct_fields"]
    assert "structured_payload.failure_context" in event_payload["field_recovery"]["inferred_fields"]
    assert "recovery_mode" in event_payload["field_recovery"]["inferred_fields"]
    assert quality["field_recovery_summary"]["inferred_event_count"] == 1
    assert quality["field_recovery_summary"]["inferred_field_count"] >= 1


def _flagged_event(risk):
    return CanonicalEvent(
        id=uuid4(),
        session_id="qual-1",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.OUTPUT,
        agent_id="claude",
        action="emit",
        summary="run output",
        source_refs=[{"kind": "message_id", "value": "m1"}],
        risk_classification=risk,
    )


def _flagged_result(events):
    return AnalysisResult(
        events=events,
        graph=LineageGraph(session_id=events[0].session_id),
        inflection_node=None,
        total_events=len(events),
        flagged_events=sum(1 for e in events if e.has_risk_flags()),
    )


def test_build_canonical_analysis_emits_qualification_block_for_clean_run():
    transcript = "\n".join(
        [
            '{"sessionId":"q-1","type":"assistant","timestamp":"2026-05-04T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tool_1","name":"Read","input":{"file_path":"README.md"}}]}}',
            '{"sessionId":"q-1","type":"user","timestamp":"2026-05-04T12:00:01Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool_1","content":"file contents","is_error":false}]}}',
        ]
    )
    result = analyze_session(ClaudeCodeParser().parse(transcript))
    payload = build_canonical_analysis(
        session=_completed_session(), result=result, provenance=_provenance()
    )

    qualification = payload["qualification"]
    assert set(qualification.keys()) == KNOWN_QUALIFICATION_FIELDS
    # A clean run with no material delta is unclassified, not qualified_failure.
    assert qualification["qualification_state"] in {"unclassified", "qualified_failure"}
    assert qualification["qualification_schema_version"] == "qualification-v1"
    assert qualification["qualification_policy_version"] == "qualification-policy-v1"
    inputs = qualification["classifiability_inputs"]
    assert inputs["extraction_quality_band"] in {"high", "usable", "degraded", "insufficient_for_matching"}
    assert isinstance(inputs["has_expected_actual_delta"], bool)
    # Completeness guard extends to nested classifiability_inputs children: a new
    # nested field added to the emitter without a registry entry fails here.
    assert set(inputs.keys()) == KNOWN_CLASSIFIABILITY_INPUTS_FIELDS


def test_build_canonical_analysis_high_quality_with_material_delta_is_qualified_failure():
    risk = RiskClassification(coverage_gap=True)
    payload = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(risk)]),
        provenance=_provenance(),
    )
    qualification = payload["qualification"]
    assert qualification["qualification_state"] == "qualified_failure"
    assert qualification["qualification_reasons"] == []
    assert qualification["qualified_at"] == "2026-06-08T12:00:00+00:00"


def test_build_canonical_analysis_emits_provenance_environment_block():
    payload = build_canonical_analysis(
        session=_completed_session(metadata={"environment": "production"}),
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=_provenance(),
    )
    block = payload["provenance_environment"]
    assert set(block.keys()) == KNOWN_PROVENANCE_ENV_FIELDS
    assert block["environment_class"] == "production"
    assert block["environment_source"] == "submitter_declared"
    assert block["provenance_confidence"] == "user_claimed"


def test_build_canonical_analysis_environment_defaults_unknown_never_production():
    payload = build_canonical_analysis(
        session=_completed_session(),  # no environment metadata
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=None,  # no source_path to infer from
    )
    block = payload["provenance_environment"]
    assert block["environment_class"] == "unknown"
    assert block["environment_source"] == "absent"
    assert block["environment_class"] != "production"


def test_build_canonical_analysis_emits_delta_records_with_resolvable_refs():
    event = _flagged_event(RiskClassification(coverage_gap=True))
    payload = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([event]),
        provenance=_provenance(),
    )
    records = payload["delta_records"]
    assert records
    for record in records:
        assert set(record.keys()) == KNOWN_DELTA_RECORD_FIELDS
    material = [r for r in records if r["delta_severity"] != "none"]
    assert material
    assert any(r["delta_type"] == "missing_output" for r in material)
    # The expected_ref resolves to the real flagged event in normalized_events.
    known_ids = {e["event_id"] for e in payload["normalized_events"]}
    for record in records:
        for ref in (record["expected_ref"], record["actual_ref"]):
            assert ref is None or ref in known_ids


def test_build_canonical_analysis_no_delta_emits_no_material_sentinel():
    payload = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(RiskClassification())]),
        provenance=_provenance(),
    )
    records = payload["delta_records"]
    assert len(records) == 1
    assert records[0]["delta_type"] == "no_material_delta_detected"
    assert records[0]["delta_severity"] == "none"


def test_build_canonical_analysis_preserves_existing_delta_types_key():
    # Regression: the deterministic matcher reads expected_vs_actual_delta.delta_types.
    # delta_records is additive and must not disturb the existing block.
    payload = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=_provenance(),
    )
    delta_block = payload["expected_vs_actual_delta"]
    assert "delta_types" in delta_block
    assert "supporting_event_ids" in delta_block
    assert isinstance(delta_block["delta_types"], list)


def test_deterministic_matching_still_reads_canonical_analysis():
    # Prove the matcher runs end-to-end against the augmented payload.
    result = _flagged_result([_flagged_event(RiskClassification(coverage_gap=True))])
    payload = build_canonical_analysis(
        session=_completed_session(), result=result, provenance=_provenance()
    )
    match = build_deterministic_match(canonical_analysis=payload, result=result)
    assert isinstance(match, dict)


def test_build_canonical_analysis_does_not_leak_recurrence_or_trust_fields():
    import json

    payload = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=_provenance(),
    )
    blob = json.dumps(payload)
    for forbidden in (
        "recurrence_count",
        "pattern_maturity",
        "trust_weighted",
        "first_observation_at",
        "trust_band",
        "final_learning_weight",
    ):
        assert forbidden not in blob, f"OSS boundary leak: {forbidden}"


def test_qualification_audit_trail_uses_provenance_timestamp():
    # Re-analysing with a newer ingest stamps a newer qualified_at; the policy
    # version is stable so aggregations never mix policies.
    risk = RiskClassification(coverage_gap=True)
    first = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(risk)]),
        provenance=_provenance(),
    )
    later = IngestProvenance(
        transcript_hash="hash-1",
        source_session_id="src-1",
        source_path=None,
        parser_version="claude_code@2",
        ingested_at=datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc),
    )
    second = build_canonical_analysis(
        session=_completed_session(),
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=later,
    )
    assert first["qualification"]["qualified_at"] != second["qualification"]["qualified_at"]
    assert (
        first["qualification"]["qualification_policy_version"]
        == second["qualification"]["qualification_policy_version"]
    )


def test_oss_serialization_strips_internal_and_teams_fields():
    payload = build_canonical_analysis(
        session=_completed_session(metadata={"environment": "production"}),
        result=_flagged_result([_flagged_event(RiskClassification(coverage_gap=True))]),
        provenance=_provenance(),
    )
    oss = apply_visibility(payload, tier="oss")
    qualification = oss["qualification"]
    assert "qualification_state" in qualification
    assert "qualification_policy_version" not in qualification
    assert "qualification_reasons" not in qualification
    assert oss["provenance_environment"] == {"environment_class": "production"}
    # delta_records stay fully visible at the oss tier
    assert oss["delta_records"]
