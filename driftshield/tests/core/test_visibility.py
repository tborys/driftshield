"""Tier-aware visibility enforcement for the qualification/provenance/delta seam."""

from driftshield.core.visibility import (
    KNOWN_CLASSIFIABILITY_INPUTS_FIELDS,
    KNOWN_DELTA_RECORD_FIELDS,
    KNOWN_PROVENANCE_ENV_FIELDS,
    KNOWN_QUALIFICATION_FIELDS,
    VISIBILITY_REGISTRY,
    apply_visibility,
    visibility_class_for,
)


def _sample_canonical():
    return {
        "qualification": {
            "qualification_state": "qualified_failure",
            "qualification_reasons": [],
            "qualified_at": "2026-06-08T00:00:00+00:00",
            "classifiability_inputs": {
                "extraction_quality_band": "high",
                "coverage_ratio": 0.9,
                "event_count": 4,
                "has_expected_actual_delta": True,
                "ambiguity_count": 0,
            },
            "qualification_schema_version": "v1",
            "qualification_policy_version": "policy-v1",
        },
        "provenance_environment": {
            "provenance_confidence": "user_claimed",
            "environment_class": "production",
            "environment_source": "submitter_declared",
        },
        "delta_records": [
            {
                "delta_type": "missing_output",
                "delta_severity": "material",
                "expected_ref": "11111111-1111-1111-1111-111111111111",
                "actual_ref": None,
                "delta_summary": "Expected output absent.",
                "delta_confidence": 0.8,
            }
        ],
        # an untouched existing block must survive unchanged
        "analysis_session": {"session_id": "abc"},
    }


class TestRegistryCompleteness:
    def test_every_known_qualification_field_has_a_class(self):
        for field in KNOWN_QUALIFICATION_FIELDS:
            assert visibility_class_for("qualification", field) is not None, field

    def test_every_known_provenance_env_field_has_a_class(self):
        for field in KNOWN_PROVENANCE_ENV_FIELDS:
            assert visibility_class_for("provenance_environment", field) is not None, field

    def test_every_known_delta_record_field_has_a_class(self):
        for field in KNOWN_DELTA_RECORD_FIELDS:
            assert visibility_class_for("delta_records.[]", field) is not None, field

    def test_every_known_classifiability_input_field_has_a_class(self):
        # Nested fields inside classifiability_inputs must be individually
        # registered, not covered only by the parent object's class.
        for field in KNOWN_CLASSIFIABILITY_INPUTS_FIELDS:
            assert (
                visibility_class_for("qualification.classifiability_inputs", field) is not None
            ), field

    def test_registry_only_uses_valid_tier_names(self):
        valid = {"oss", "teams", "enterprise", "internal_only"}
        for path, tier in VISIBILITY_REGISTRY.items():
            assert tier in valid, f"{path} -> {tier}"

    def test_unregistered_field_has_no_class(self):
        # A new field added to a block without a registry entry returns None.
        # The build-side completeness test (test_canonical_analysis) asserts
        # the emitted field set equals the KNOWN_* set, so an unregistered field
        # surfaces as a failure rather than silently shipping.
        assert visibility_class_for("qualification", "some_unregistered_field") is None


class TestApplyVisibilityOssTier:
    def test_oss_keeps_state_and_environment_class(self):
        filtered = apply_visibility(_sample_canonical(), tier="oss")
        assert filtered["qualification"]["qualification_state"] == "qualified_failure"
        assert filtered["provenance_environment"]["environment_class"] == "production"

    def test_oss_strips_teams_fields(self):
        filtered = apply_visibility(_sample_canonical(), tier="oss")
        q = filtered["qualification"]
        assert "qualification_reasons" not in q
        assert "classifiability_inputs" not in q
        assert "qualified_at" not in q
        assert "qualification_schema_version" not in q
        pe = filtered["provenance_environment"]
        assert "provenance_confidence" not in pe
        assert "environment_source" not in pe

    def test_oss_strips_internal_only_policy_version(self):
        filtered = apply_visibility(_sample_canonical(), tier="oss")
        assert "qualification_policy_version" not in filtered["qualification"]

    def test_oss_keeps_delta_records_and_all_their_fields(self):
        filtered = apply_visibility(_sample_canonical(), tier="oss")
        record = filtered["delta_records"][0]
        assert record["delta_type"] == "missing_output"
        assert record["delta_confidence"] == 0.8
        assert record["actual_ref"] is None

    def test_oss_preserves_unrelated_blocks(self):
        filtered = apply_visibility(_sample_canonical(), tier="oss")
        assert filtered["analysis_session"] == {"session_id": "abc"}


class TestApplyVisibilityHigherTiers:
    def test_teams_keeps_reasons_and_provenance_confidence(self):
        filtered = apply_visibility(_sample_canonical(), tier="teams")
        assert filtered["qualification"]["qualification_reasons"] == []
        assert filtered["qualification"]["classifiability_inputs"]["extraction_quality_band"] == "high"
        assert filtered["provenance_environment"]["provenance_confidence"] == "user_claimed"

    def test_unregistered_nested_classifiability_field_is_stripped(self):
        # A future nested field with no registry entry must NOT leak through the
        # parent object's tier gate. Unregistered nested fields are withheld
        # rather than exposed.
        canonical = _sample_canonical()
        canonical["qualification"]["classifiability_inputs"]["secret_diagnostic"] = "LEAK"
        for tier in ("oss", "teams", "enterprise", "internal_only"):
            filtered = apply_visibility(canonical, tier=tier)
            inputs = filtered["qualification"].get("classifiability_inputs", {})
            assert "secret_diagnostic" not in inputs, tier

    def test_teams_still_strips_internal_only(self):
        filtered = apply_visibility(_sample_canonical(), tier="teams")
        assert "qualification_policy_version" not in filtered["qualification"]

    def test_internal_only_exposes_policy_version(self):
        filtered = apply_visibility(_sample_canonical(), tier="internal_only")
        assert filtered["qualification"]["qualification_policy_version"] == "policy-v1"

    def test_does_not_mutate_input(self):
        canonical = _sample_canonical()
        apply_visibility(canonical, tier="oss")
        # original retains the teams-tier field
        assert "qualification_reasons" in canonical["qualification"]

    def test_unknown_tier_defaults_to_oss(self):
        filtered = apply_visibility(_sample_canonical(), tier="not-a-tier")
        assert filtered["qualification"]["qualification_state"] == "qualified_failure"
        assert "qualification_reasons" not in filtered["qualification"]


class TestEmittedFieldsMatchRegistry:
    """A new field added to an emitted block without a registry + KNOWN_* entry must fail."""

    def test_qualification_emitted_fields_match_known_set(self):
        emitted = set(_sample_canonical()["qualification"].keys())
        assert emitted == KNOWN_QUALIFICATION_FIELDS

    def test_provenance_env_emitted_fields_match_known_set(self):
        emitted = set(_sample_canonical()["provenance_environment"].keys())
        assert emitted == KNOWN_PROVENANCE_ENV_FIELDS

    def test_delta_record_emitted_fields_match_known_set(self):
        emitted = set(_sample_canonical()["delta_records"][0].keys())
        assert emitted == KNOWN_DELTA_RECORD_FIELDS

    def test_classifiability_inputs_emitted_fields_match_known_set(self):
        emitted = set(_sample_canonical()["qualification"]["classifiability_inputs"].keys())
        assert emitted == KNOWN_CLASSIFIABILITY_INPUTS_FIELDS
