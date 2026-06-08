"""Structured delta-record tests (driftshield#68).

Delta records are an additive structure on the canonical payload. They carry a
closed DeltaType, a severity band, and event_id refs that resolve against
normalized_events (nulled safely when an event was lost, e.g. to redaction).
"""

from uuid import uuid4

from driftshield.core.canonical_analysis import _refine_delta_records
from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from datetime import datetime, timezone


def _normalized(event_ids):
    return [{"event_id": eid} for eid in event_ids]


def _event(event_id, *, risk=None, failure=None, tool=None, action="Read"):
    return CanonicalEvent(
        id=event_id,
        session_id="s",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action=action,
        risk_classification=risk,
        failure_context=failure,
        tool_activity=tool,
    )


def _result(events):
    return AnalysisResult(
        events=events,
        graph=LineageGraph(session_id="s"),
        inflection_node=None,
        total_events=len(events),
        flagged_events=sum(1 for e in events if e.has_risk_flags()),
    )


class TestNoMaterialDelta:
    def test_no_signals_emits_single_no_material_sentinel(self):
        records = _refine_delta_records(
            _result([_event(uuid4())]),
            normalized_events=_normalized(["x"]),
            delta_types=[],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        assert len(records) == 1
        assert records[0]["delta_type"] == "no_material_delta_detected"
        assert records[0]["delta_severity"] == "none"
        assert records[0]["expected_ref"] is None
        assert records[0]["actual_ref"] is None


class TestDeltaTypeMapping:
    def test_coverage_gap_maps_to_missing_output(self):
        eid = uuid4()
        risk = RiskClassification(coverage_gap=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["missing_required_action"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        types = {r["delta_type"] for r in records}
        assert "missing_output" in types
        assert "no_material_delta_detected" not in types

    def test_policy_violation_maps_to_invalid_schema_severe(self):
        eid = uuid4()
        risk = RiskClassification(constraint_violation=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["policy_violation"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        match = next(r for r in records if r["delta_type"] == "invalid_schema")
        assert match["delta_severity"] == "severe"

    def test_policy_divergence_maps_to_incorrect_output(self):
        eid = uuid4()
        risk = RiskClassification(policy_divergence=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["wrong_action"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        assert "incorrect_output" in {r["delta_type"] for r in records}


class TestRefResolution:
    def test_ref_present_in_normalized_events_resolves(self):
        eid = uuid4()
        risk = RiskClassification(coverage_gap=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["missing_required_action"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        material = next(r for r in records if r["delta_severity"] != "none")
        assert material["expected_ref"] == str(eid)

    def test_ref_lost_to_redaction_is_nulled_safely(self):
        # The flagged event is NOT in normalized_events (simulating an event
        # dropped during redaction). The ref must null, not dangle.
        eid = uuid4()
        risk = RiskClassification(coverage_gap=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized(["some-other-surviving-event"]),
            delta_types=["missing_required_action"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        for record in records:
            for ref in (record["expected_ref"], record["actual_ref"]):
                if ref is not None:
                    assert ref in {"some-other-surviving-event"}
        material = next(r for r in records if r["delta_severity"] != "none")
        assert material["expected_ref"] is None

    def test_oss_refs_only_point_at_surviving_events(self):
        # Stronger statement of the redaction-safety invariant: no emitted ref
        # may point at an event id that is absent from normalized_events.
        e1, e2 = uuid4(), uuid4()
        risk = RiskClassification(coverage_gap=True, policy_divergence=True)
        records = _refine_delta_records(
            _result([_event(e1, risk=risk)]),
            normalized_events=_normalized([str(e2)]),  # e1 redacted out
            delta_types=["missing_required_action", "wrong_action"],
            overall_quality_band="high",
            coverage_ratio=0.9,
        )
        surviving = {str(e2)}
        for record in records:
            for ref in (record["expected_ref"], record["actual_ref"]):
                assert ref is None or ref in surviving


class TestDeltaConfidence:
    def test_confidence_bounded_by_coverage_ratio(self):
        eid = uuid4()
        risk = RiskClassification(coverage_gap=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["missing_required_action"],
            overall_quality_band="high",
            coverage_ratio=0.4,
        )
        for record in records:
            assert record["delta_confidence"] <= 0.4 + 1e-9

    def test_usable_band_caps_confidence_below_high(self):
        eid = uuid4()
        risk = RiskClassification(coverage_gap=True)
        records = _refine_delta_records(
            _result([_event(eid, risk=risk)]),
            normalized_events=_normalized([str(eid)]),
            delta_types=["missing_required_action"],
            overall_quality_band="usable",
            coverage_ratio=0.95,
        )
        for record in records:
            assert record["delta_confidence"] <= 0.75 + 1e-9
