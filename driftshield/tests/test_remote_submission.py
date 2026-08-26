"""Unit tests for the D19 unauthenticated OSS submission module."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib import error

import pytest

from driftshield.intake_contract import (
    DEFAULT_WORKFLOW_REFERENCE,
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    OssSubmissionRequest,
)
from driftshield.remote_submission import (
    SERVER_CONTRACT_VERSION_HEADER,
    OssRemoteSubmissionConfig,
    RemoteSubmissionError,
    build_oss_submission_request,
    post_oss_submission,
)


_OSS_INTAKE_URL = "https://example.test/v1/oss/submissions"


def _config() -> OssRemoteSubmissionConfig:
    return OssRemoteSubmissionConfig(intake_url=_OSS_INTAKE_URL)


def test_build_oss_submission_request_phase3g_v1_shape():
    """Builder produces a phase3g.v1 envelope with the default workflow ref."""
    payload = {"session_id": "sess-1", "metadata": {"foo": "bar"}}

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload=payload,
    )

    assert isinstance(request, OssSubmissionRequest)
    assert request.envelope_contract_version == SUPPORTED_CONTRACT_VERSION == "phase3g.v1"

    envelope = request.envelope
    assert envelope.schema_version == SUPPORTED_CONTRACT_VERSION
    assert envelope.source_session_id == "sess-1"
    assert envelope.workflow_reference == DEFAULT_WORKFLOW_REFERENCE
    assert envelope.agent_id is None
    assert envelope.model_name is None
    assert envelope.model_version is None
    assert envelope.payload["session_id"] == "sess-1"
    assert envelope.payload["metadata"] == {"foo": "bar"}

    assert envelope.redaction_manifest.manifest_version == REDACTION_MANIFEST_VERSION
    assert envelope.redaction_manifest.redaction_applied is True
    assert set(envelope.redaction_manifest.redacted_fields) == REQUIRED_REDACTION_FIELDS


def test_build_oss_submission_request_threads_provenance_fields():
    """agent_id / model_name / model_version are surfaced on the envelope when supplied."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
        agent_id="agent-42",
        model_name="claude-opus-4-7",
        model_version="2026-05",
    )

    envelope = request.envelope
    assert envelope.agent_id == "agent-42"
    assert envelope.model_name == "claude-opus-4-7"
    assert envelope.model_version == "2026-05"


def test_build_oss_submission_request_threads_session_observed_at():
    """driftshield#174: session_observed_at is surfaced on the envelope
    when supplied, as a real datetime parsed from the ISO 8601 string."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
        session_observed_at="2026-01-01T00:05:30+00:00",
    )

    envelope = request.envelope
    assert envelope.session_observed_at is not None
    assert envelope.session_observed_at.isoformat() == "2026-01-01T00:05:30+00:00"


def test_build_oss_submission_request_session_observed_at_absent_by_default():
    """No timestamp supplied => the field stays unset, not a fallback value."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    assert request.envelope.session_observed_at is None


def test_build_oss_submission_request_workflow_reference_override():
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
        workflow_reference="checkout-flow",
    )

    assert request.envelope.workflow_reference == "checkout-flow"


def test_build_oss_submission_request_emits_manifest_v2_with_provenance():
    """Manifest v2 carries redactor + ruleset versions for server-side provenance."""
    from driftshield.recursive_redactor import (
        REDACTION_RULESET_VERSION,
        REDACTOR_VERSION,
    )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1", "metadata": {"foo": "bar"}},
    )

    manifest = request.envelope.redaction_manifest
    assert manifest.manifest_version == "redaction-manifest.v2"
    assert manifest.redactor_version == REDACTOR_VERSION
    assert manifest.redaction_ruleset_version == REDACTION_RULESET_VERSION


def test_build_oss_submission_request_has_no_installation_id_or_consent_state():
    """D19 contract: request must NOT carry installation_id or consent_state."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    serialised = json.loads(request.model_dump_json())
    assert "installation_id" not in serialised
    assert "consent_state" not in serialised
    assert set(serialised.keys()) == {"envelope_contract_version", "envelope"}


def test_build_oss_submission_request_payload_size_bytes_is_exact():
    """payload_size_bytes must match the canonical encoding rule used by the intake validator."""
    payload = {"session_id": "sess-1", "metadata": {"foo": "bar"}}

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload=payload,
    )

    expected = json.dumps(
        request.envelope.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert request.envelope.payload_size_bytes == len(expected)


class _FakeHttpResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_post_oss_submission_happy_path():
    captured: dict[str, Any] = {}

    def fake_opener(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.headers)
        captured["body"] = req.data
        return _FakeHttpResponse(
            json.dumps({"submission_id": "sub_abc", "processing_status": "received"}).encode("utf-8"),
            headers={SERVER_CONTRACT_VERSION_HEADER: SUPPORTED_CONTRACT_VERSION},
        )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    result = post_oss_submission(config=_config(), submission=request, opener=fake_opener)

    assert result.response.submission_id == "sub_abc"
    assert result.response.processing_status == "received"
    assert result.server_contract_version == SUPPORTED_CONTRACT_VERSION
    assert captured["url"] == _OSS_INTAKE_URL
    assert captured["method"] == "POST"
    # urllib.request lowercases header keys when stored on the Request object.
    # D19 contract: NO X-API-Key, NO Authorization.
    assert "X-api-key" not in captured["headers"]
    assert "Authorization" not in captured["headers"]
    assert captured["headers"].get("Content-type") == "application/json"
    decoded = json.loads(captured["body"].decode("utf-8"))
    assert "installation_id" not in decoded
    assert "consent_state" not in decoded
    assert decoded["envelope_contract_version"] == SUPPORTED_CONTRACT_VERSION


def test_post_oss_submission_surfaces_deprecated_server_header():
    """OSS client surfaces a server-side phase3f.v1 advertisement so the CLI
    can log a deprecation warning. AC5."""

    def fake_opener(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(
            json.dumps({"submission_id": "sub_abc", "processing_status": "received"}).encode("utf-8"),
            headers={SERVER_CONTRACT_VERSION_HEADER: "phase3f.v1"},
        )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    result = post_oss_submission(config=_config(), submission=request, opener=fake_opener)

    assert result.server_contract_version == "phase3f.v1"


def test_post_oss_submission_server_contract_version_absent_when_header_missing():
    def fake_opener(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(
            json.dumps({"submission_id": "sub_abc", "processing_status": "received"}).encode("utf-8"),
        )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    result = post_oss_submission(config=_config(), submission=request, opener=fake_opener)

    assert result.server_contract_version is None


def test_post_oss_submission_http_error_raises_remote_submission_error():
    def fake_opener(req: Any) -> _FakeHttpResponse:
        raise error.HTTPError(
            url=_OSS_INTAKE_URL,
            code=422,
            msg="Unprocessable Content",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"detail":"invalid_redaction_manifest"}'),
        )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    with pytest.raises(RemoteSubmissionError) as exc_info:
        post_oss_submission(config=_config(), submission=request, opener=fake_opener)
    assert "HTTP 422" in str(exc_info.value)
    assert "invalid_redaction_manifest" in str(exc_info.value)


def test_post_oss_submission_url_error_raises_remote_submission_error():
    def fake_opener(req: Any) -> _FakeHttpResponse:
        raise error.URLError("Name or service not known")

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    with pytest.raises(RemoteSubmissionError) as exc_info:
        post_oss_submission(config=_config(), submission=request, opener=fake_opener)
    assert "unreachable" in str(exc_info.value)


def test_post_oss_submission_non_json_response_raises():
    def fake_opener(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(b"<html>oops</html>")

    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )

    with pytest.raises(RemoteSubmissionError) as exc_info:
        post_oss_submission(config=_config(), submission=request, opener=fake_opener)
    assert "non-JSON" in str(exc_info.value)


# ---------------------------------------------------------------------------
# signature_summary plumbing
# ---------------------------------------------------------------------------


from unittest.mock import patch  # noqa: E402

from driftshield.intake_contract import (  # noqa: E402
    SIGNATURE_SUMMARY_VERSION,
    SignatureSummary,
    SignatureSummaryEntry,
)


def _summary_with_one_entry() -> SignatureSummary:
    return SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=[
            SignatureSummaryEntry(
                signature_id="sig-abc",
                match_status="matched",
                community_pack_id="community-general",
                community_pack_version="1.0.0",
                matcher_id="phase-3g-deterministic-v1",
                matcher_version="phase-3g-deterministic-rules-v1",
                confidence=0.9,
                confidence_band="high",
            )
        ],
    )


def test_build_oss_submission_request_no_signature_summary():
    """Default invocation produces an envelope with signature_summary=None."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )
    assert request.envelope.signature_summary is None


def test_build_oss_submission_request_populates_signature_summary():
    summary = _summary_with_one_entry()
    request = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
        signature_summary=summary,
    )
    assert request.envelope.signature_summary is not None
    assert request.envelope.signature_summary.schema_version == SIGNATURE_SUMMARY_VERSION
    assert request.envelope.signature_summary.matches[0].signature_id == "sig-abc"

    # Serialised payload carries the block alongside ``payload``.
    encoded = json.loads(request.model_dump_json())
    assert "signature_summary" in encoded["envelope"]
    assert encoded["envelope"]["signature_summary"]["matches"][0]["signature_id"] == "sig-abc"


def test_derive_oss_inline_submit_url_from_canonical_intake():
    from driftshield.remote_submission import derive_oss_inline_submit_url

    assert (
        derive_oss_inline_submit_url("https://api.example/v1/intake")
        == "https://api.example/v1/oss/submissions"
    )


def test_derive_oss_inline_submit_url_idempotent_on_oss_route():
    from driftshield.remote_submission import derive_oss_inline_submit_url

    assert (
        derive_oss_inline_submit_url("https://api.example/v1/oss/submissions")
        == "https://api.example/v1/oss/submissions"
    )
    assert (
        derive_oss_inline_submit_url("https://api.example/v1/oss/submissions/")
        == "https://api.example/v1/oss/submissions"
    )


def test_derive_oss_inline_submit_url_appends_to_bare_base():
    from driftshield.remote_submission import derive_oss_inline_submit_url

    assert (
        derive_oss_inline_submit_url("https://api.example")
        == "https://api.example/v1/oss/submissions"
    )


def test_post_oss_submission_routes_v1_intake_to_oss_submissions():
    """The canonical /v1/intake base must NOT be hit by the inline OSS POST:
    that route is the authenticated intake and 422s on unauthenticated inline
    submits. The inline lane derives the OSS route from the same base."""
    captured: dict[str, Any] = {}

    def fake_opener(req: Any) -> _FakeHttpResponse:
        captured["url"] = req.full_url
        return _FakeHttpResponse(
            json.dumps(
                {"submission_id": "sub_abc", "processing_status": "received"}
            ).encode("utf-8"),
            headers={SERVER_CONTRACT_VERSION_HEADER: SUPPORTED_CONTRACT_VERSION},
        )

    submission = build_oss_submission_request(
        source_session_id="sess-1",
        redacted_payload={"session_id": "sess-1"},
    )
    post_oss_submission(
        config=OssRemoteSubmissionConfig(intake_url="https://api.example/v1/intake"),
        submission=submission,
        opener=fake_opener,
    )

    assert captured["url"] == "https://api.example/v1/oss/submissions"


def _openclaw_event(event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": event_type,
        "runId": "run-1",
        "traceId": "trace-1",
        "schemaVersion": 1,
        "seq": 1,
        "source": "runtime",
        "sessionId": "8ad36b0f-9181-4961-9263-770f657db9f5",
        "provider": "openai-codex",
        "modelId": "gpt-5.4",
        "modelApi": "openai-codex-responses",
        "data": data or {},
    }


def _openclaw_payload() -> dict[str, Any]:
    return {
        "session_id": "8ad36b0f-9181-4961-9263-770f657db9f5",
        "events": [
            _openclaw_event("session.started", {"agentId": "engineering", "trigger": "cron"}),
            _openclaw_event("prompt.submitted", {"prompt": "run the heartbeat"}),
            _openclaw_event("session.ended", {"status": "success"}),
        ],
    }


