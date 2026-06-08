"""Qualification state-machine unit tests (driftshield#68).

These test the pure ``_compute_qualification_state`` decision function directly so
the bars are pinned independently of parser machinery. End-to-end emission is
covered in test_canonical_analysis.
"""

from driftshield.core.canonical_analysis import _compute_qualification_state


def _events(count, *, recovery_mode="direct", missing=False):
    return [
        {
            "event_id": f"e{i}",
            "recovery_mode": recovery_mode,
            "missing_fields": ["x"] if missing else [],
        }
        for i in range(count)
    ]


class TestDegradedHardBar:
    def test_degraded_band_forces_unclassified_even_with_material_delta(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="degraded",
            integrity_status="complete",
            delta_types=["missing_required_action"],  # a material delta is present
            normalized_events=_events(5),
        )
        assert state == "unclassified"
        assert "extraction_quality_degraded" in reasons

    def test_insufficient_band_forces_unclassified(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="insufficient_for_matching",
            integrity_status="complete",
            delta_types=["wrong_action"],
            normalized_events=_events(3),
        )
        assert state == "unclassified"
        assert "extraction_quality_degraded" in reasons

    def test_degraded_never_qualified_failure_regardless_of_signals(self):
        # The mitigation in the spec: a high-confidence candidate must NOT upgrade
        # a degraded run. Even with every material signal, degraded stays out.
        state, _ = _compute_qualification_state(
            overall_quality_band="degraded",
            integrity_status="complete",
            delta_types=["missing_required_action", "wrong_action", "policy_violation"],
            normalized_events=_events(8),
        )
        assert state != "qualified_failure"


class TestNotClassifiable:
    def test_no_events_returns_not_classifiable(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="high",
            integrity_status="complete",
            delta_types=["missing_required_action"],
            normalized_events=[],
        )
        assert state == "not_classifiable"
        assert "no_events" in reasons


class TestQualifiedFailure:
    def test_high_band_material_delta_complete_integrity_qualifies(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="high",
            integrity_status="complete",
            delta_types=["missing_required_action"],
            normalized_events=_events(4),
        )
        assert state == "qualified_failure"
        assert reasons == []

    def test_usable_band_material_delta_recovered_integrity_qualifies(self):
        # "usable" passes the extraction bar; "recovered" is acceptable integrity.
        state, _ = _compute_qualification_state(
            overall_quality_band="usable",
            integrity_status="recovered",
            delta_types=["wrong_action"],
            normalized_events=_events(4),
        )
        assert state == "qualified_failure"


class TestUnclassifiedNoDelta:
    def test_high_band_no_delta_returns_unclassified_no_material_delta(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="high",
            integrity_status="complete",
            delta_types=[],
            normalized_events=_events(4),
        )
        assert state == "unclassified"
        assert "no_material_delta_detected" in reasons

    def test_high_band_only_no_material_marker_returns_unclassified(self):
        state, reasons = _compute_qualification_state(
            overall_quality_band="high",
            integrity_status="complete",
            delta_types=["no_material_delta_detected"],
            normalized_events=_events(4),
        )
        assert state == "unclassified"
        assert "no_material_delta_detected" in reasons
