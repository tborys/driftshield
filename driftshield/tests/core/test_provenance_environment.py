"""Provenance confidence + environment classification tests (driftshield#68)."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.canonical_analysis import _compute_provenance_and_environment
from driftshield.core.models import Session, SessionStatus
from driftshield.db.persistence import IngestProvenance


def _session(metadata=None, external_id=None):
    return Session(
        id=uuid4(),
        agent_id="claude",
        started_at=datetime.now(timezone.utc),
        external_id=external_id,
        status=SessionStatus.COMPLETED,
        metadata=metadata or {},
    )


def _provenance(source_path=None, source_session_id="src-1"):
    return IngestProvenance(
        transcript_hash="hash-1",
        source_session_id=source_session_id,
        source_path=source_path,
        parser_version="claude_code@1",
        ingested_at=datetime.now(timezone.utc),
    )


class TestProvenanceConfidence:
    def test_no_provenance_no_external_id_is_unknown(self):
        block = _compute_provenance_and_environment(_session(), None)
        assert block["provenance_confidence"] == "unknown"

    def test_no_provenance_with_external_id_is_inferred(self):
        block = _compute_provenance_and_environment(_session(external_id="ext-1"), None)
        assert block["provenance_confidence"] == "inferred"

    def test_provenance_present_is_user_claimed(self):
        # IngestProvenance carries no connector signal today, so an attested
        # provenance is user_claimed, never connector_verified.
        block = _compute_provenance_and_environment(_session(), _provenance())
        assert block["provenance_confidence"] == "user_claimed"


class TestEnvironmentClassification:
    def test_declared_production_is_returned_not_defaulted(self):
        block = _compute_provenance_and_environment(
            _session(metadata={"environment": "production"}), _provenance()
        )
        assert block["environment_class"] == "production"
        assert block["environment_source"] == "submitter_declared"

    def test_declared_test_is_submitter_declared(self):
        block = _compute_provenance_and_environment(
            _session(metadata={"environment": "test"}), _provenance()
        )
        assert block["environment_class"] == "test"
        assert block["environment_source"] == "submitter_declared"

    def test_declared_value_outside_closed_set_is_not_trusted(self):
        # An unrecognised declared value must not pass through as-is; it falls to
        # inference / unknown rather than minting a new environment class.
        block = _compute_provenance_and_environment(
            _session(metadata={"environment": "prod-eu-west"}), _provenance()
        )
        assert block["environment_class"] != "prod-eu-west"

    def test_demo_path_infers_demo(self):
        block = _compute_provenance_and_environment(
            _session(), _provenance(source_path="/home/u/demo/run.jsonl")
        )
        assert block["environment_class"] == "demo"
        assert block["environment_source"] == "inferred"

    def test_test_path_infers_test(self):
        block = _compute_provenance_and_environment(
            _session(), _provenance(source_path="/repo/test/run.jsonl")
        )
        assert block["environment_class"] == "test"
        assert block["environment_source"] == "inferred"

    def test_unrecognised_path_is_unknown_inferred(self):
        block = _compute_provenance_and_environment(
            _session(), _provenance(source_path="/home/u/projects/app/run.jsonl")
        )
        assert block["environment_class"] == "unknown"
        assert block["environment_source"] == "inferred"

    def test_no_signal_is_unknown_absent_never_production(self):
        block = _compute_provenance_and_environment(_session(), None)
        assert block["environment_class"] == "unknown"
        assert block["environment_source"] == "absent"
        assert block["environment_class"] != "production"

    def test_declared_environment_beats_path_inference(self):
        block = _compute_provenance_and_environment(
            _session(metadata={"environment": "production"}),
            _provenance(source_path="/home/u/demo/run.jsonl"),
        )
        assert block["environment_class"] == "production"
        assert block["environment_source"] == "submitter_declared"
