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
    redact_payload,
    redact_payload_with_manifest,
)


_OSS_INTAKE_URL = "https://example.test/v1/oss/submissions"


def _config() -> OssRemoteSubmissionConfig:
    return OssRemoteSubmissionConfig(intake_url=_OSS_INTAKE_URL)


def test_redact_payload_strips_required_fields():
    payload = {
        "session_id": "sess-1",
        "prompts": [{"role": "user", "content": "secret"}],
        "responses": [{"role": "assistant", "content": "also secret"}],
        "user_identifiers": ["alice@example.test"],
        "metadata": {"foo": "bar"},
    }

    redacted, redacted_fields = redact_payload(payload)

    assert "prompts" not in redacted
    assert "responses" not in redacted
    assert "user_identifiers" not in redacted
    assert redacted["session_id"] == "sess-1"
    assert redacted["metadata"] == {"foo": "bar"}
    assert set(redacted_fields) == REQUIRED_REDACTION_FIELDS


def test_redact_payload_strips_nested_content_and_text_keys():
    payload = {
        "session_id": "sess-1",
        "events": [
            {"type": "user", "content": "MY SECRET PROMPT", "ts": 1},
            {"type": "assistant", "text": "MY SECRET RESPONSE", "ts": 2},
        ],
    }

    redacted, _ = redact_payload(payload)

    serialised = json.dumps(redacted)
    assert "MY SECRET PROMPT" not in serialised
    assert "MY SECRET RESPONSE" not in serialised
    assert redacted["session_id"] == "sess-1"
    assert [e["type"] for e in redacted["events"]] == ["user", "assistant"]
    assert [e["ts"] for e in redacted["events"]] == [1, 2]
    for event in redacted["events"]:
        assert "content" not in event
        assert "text" not in event


def test_redact_payload_strips_deeply_nested_sensitive_keys():
    payload = {
        "level_1": {
            "level_2": {
                "level_3": {
                    "level_4": {
                        "content": "DEEP_SECRET",
                        "keep": "safe_value",
                    }
                }
            }
        }
    }

    redacted, _ = redact_payload(payload)

    assert "DEEP_SECRET" not in json.dumps(redacted)
    assert redacted["level_1"]["level_2"]["level_3"]["level_4"] == {"keep": "safe_value"}


def test_redact_payload_removes_claude_code_prompt_response_strings():
    """Realistic Claude Code session shape: events[].content carries prompts/responses."""
    payload = {
        "session_id": "claude-sess-abc",
        "events": [
            {
                "type": "user",
                "content": "Please refactor the auth middleware to use JWT",
                "timestamp": "2026-05-17T10:00:00Z",
            },
            {
                "type": "assistant",
                "content": "Here's the refactored middleware with JWT validation...",
                "timestamp": "2026-05-17T10:00:05Z",
                "tool_calls": [
                    {"name": "edit", "arguments": {"file": "/src/auth.py"}},
                ],
            },
        ],
        "metadata": {"model": "claude-opus-4-7"},
    }

    redacted, _ = redact_payload(payload)
    serialised = json.dumps(redacted)

    assert "Please refactor the auth middleware to use JWT" not in serialised
    assert "Here's the refactored middleware with JWT validation..." not in serialised
    assert redacted["session_id"] == "claude-sess-abc"
    assert redacted["metadata"] == {"model": "claude-opus-4-7"}
    assert [e["type"] for e in redacted["events"]] == ["user", "assistant"]


def test_redact_payload_handles_none_and_empty_values():
    payload = {
        "session_id": "sess-1",
        "empty_dict": {},
        "empty_list": [],
        "none_value": None,
        "events": [],
    }

    redacted, _ = redact_payload(payload)

    assert redacted == payload


def test_build_oss_submission_request_redacts_nested_content_before_manifest():
    """The envelope-building path must redact nested content before the manifest is built."""
    payload = {
        "session_id": "sess-1",
        "events": [
            {"type": "user", "content": "LEAK_CANARY_PROMPT"},
            {"type": "assistant", "content": "LEAK_CANARY_RESPONSE"},
        ],
    }

    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload=payload,
    )

    serialised = request.envelope.model_dump_json()
    assert "LEAK_CANARY_PROMPT" not in serialised
    assert "LEAK_CANARY_RESPONSE" not in serialised
    # Public manifest contract is unchanged: still advertises REQUIRED_REDACTION_FIELDS.
    assert set(request.envelope.redaction_manifest.redacted_fields) == REQUIRED_REDACTION_FIELDS
    assert request.envelope.redaction_manifest.redaction_applied is True
    # payload_size_bytes must reflect the redacted payload, not the original.
    expected_bytes = json.dumps(
        request.envelope.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert request.envelope.payload_size_bytes == len(expected_bytes)


def test_redact_payload_manifest_advertises_superset_even_if_missing():
    payload = {"session_id": "sess-1", "metadata": {"foo": "bar"}}

    redacted, redacted_fields = redact_payload(payload)

    assert redacted == payload
    assert set(redacted_fields) == REQUIRED_REDACTION_FIELDS


def test_build_oss_submission_request_phase3g_v1_shape():
    """Builder produces a phase3g.v1 envelope with the default workflow ref."""
    payload = {
        "session_id": "sess-1",
        "prompts": ["should be stripped"],
        "responses": ["also stripped"],
        "user_identifiers": ["alice@example.test"],
        "metadata": {"foo": "bar"},
    }

    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload=payload,
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
    assert "prompts" not in envelope.payload
    assert "responses" not in envelope.payload
    assert "user_identifiers" not in envelope.payload
    assert envelope.payload["session_id"] == "sess-1"
    assert envelope.payload["metadata"] == {"foo": "bar"}

    assert envelope.redaction_manifest.manifest_version == REDACTION_MANIFEST_VERSION
    assert envelope.redaction_manifest.redaction_applied is True
    assert set(envelope.redaction_manifest.redacted_fields) == REQUIRED_REDACTION_FIELDS


def test_build_oss_submission_request_threads_provenance_fields():
    """agent_id / model_name / model_version are surfaced on the envelope when supplied."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
        agent_id="agent-42",
        model_name="claude-opus-4-7",
        model_version="2026-05",
    )

    envelope = request.envelope
    assert envelope.agent_id == "agent-42"
    assert envelope.model_name == "claude-opus-4-7"
    assert envelope.model_version == "2026-05"


def test_build_oss_submission_request_workflow_reference_override():
    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1", "metadata": {"foo": "bar"}},
    )

    manifest = request.envelope.redaction_manifest
    assert manifest.manifest_version == "redaction-manifest.v2"
    assert manifest.redactor_version == REDACTOR_VERSION
    assert manifest.redaction_ruleset_version == REDACTION_RULESET_VERSION


def test_build_oss_submission_request_has_no_installation_id_or_consent_state():
    """D19 contract: request must NOT carry installation_id or consent_state."""
    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
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
        payload=payload,
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
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1"},
    )

    with pytest.raises(RemoteSubmissionError) as exc_info:
        post_oss_submission(config=_config(), submission=request, opener=fake_opener)
    assert "unreachable" in str(exc_info.value)


def test_post_oss_submission_non_json_response_raises():
    def fake_opener(req: Any) -> _FakeHttpResponse:
        return _FakeHttpResponse(b"<html>oops</html>")

    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
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
        payload={"session_id": "sess-1"},
    )
    assert request.envelope.signature_summary is None


def test_build_oss_submission_request_populates_signature_summary():
    summary = _summary_with_one_entry()
    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
        signature_summary=summary,
    )
    assert request.envelope.signature_summary is not None
    assert request.envelope.signature_summary.schema_version == SIGNATURE_SUMMARY_VERSION
    assert request.envelope.signature_summary.matches[0].signature_id == "sig-abc"

    # Serialised payload carries the block alongside ``payload``.
    encoded = json.loads(request.model_dump_json())
    assert "signature_summary" in encoded["envelope"]
    assert encoded["envelope"]["signature_summary"]["matches"][0]["signature_id"] == "sig-abc"


def test_redact_call_site_passes_only_payload():
    """The redactor is invoked only with the inner payload dict, never the envelope."""
    summary = _summary_with_one_entry()
    captured: dict[str, Any] = {}

    real_redact = __import__(
        "driftshield.remote_submission", fromlist=["redact_payload"]
    ).redact_payload

    def spy(payload):
        captured["payload"] = payload
        return real_redact(payload)

    with patch("driftshield.remote_submission.redact_payload", side_effect=spy) as spied:
        build_oss_submission_request(
            source_session_id="sess-1",
            payload={"session_id": "sess-1", "metadata": {"foo": "bar"}},
            signature_summary=summary,
        )

    # Redactor saw exactly the inner payload dict; signature_summary was not
    # in the input, by construction (it is a sibling of payload, not nested).
    assert spied.call_count == 1
    inner_payload = captured["payload"]
    assert "signature_summary" not in inner_payload
    assert inner_payload["session_id"] == "sess-1"
    assert inner_payload["metadata"] == {"foo": "bar"}


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
        payload={"session_id": "sess-1"},
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


def test_detect_shape_openclaw_trajectory():
    from driftshield.remote_submission import detect_shape

    assert detect_shape(_openclaw_payload()) == "openclaw_trajectory"


def test_detect_shape_claude_code_lines_still_detect():
    from driftshield.remote_submission import detect_shape

    payload = {
        "session_id": "sess-1",
        "events": [
            {"type": "assistant", "sessionId": "sess-1", "message": {"content": []}},
            {"type": "user", "sessionId": "sess-1", "message": {"content": []}},
        ],
    }
    assert detect_shape(payload) == "claude_code"


def test_detect_shape_unrecognisable_events_are_not_claude_code():
    """Arbitrary line-delimited JSON without the type discriminator must not
    wave through the unknown-shape redaction guard as claude_code."""
    from driftshield.remote_submission import detect_shape

    payload = {"events": [{"foo": 1}, {"bar": 2}]}
    assert detect_shape(payload) is None


def test_openclaw_payload_submits_without_force_unknown_shape():
    submission = build_oss_submission_request(
        source_session_id="sess-oc",
        payload=_openclaw_payload(),
    )
    assert submission.envelope.payload["events"]


def test_derive_openclaw_provenance_extracts_agent_and_model():
    from driftshield.remote_submission import derive_openclaw_provenance

    provenance = derive_openclaw_provenance(_openclaw_payload())
    assert provenance == {
        "agent_id": "openclaw:engineering",
        "model_name": "openai-codex/gpt-5.4",
    }


def test_derive_openclaw_provenance_empty_for_other_shapes():
    from driftshield.remote_submission import derive_openclaw_provenance

    assert derive_openclaw_provenance({"session_id": "sess-1"}) == {}
    assert (
        derive_openclaw_provenance(
            {"events": [{"type": "assistant", "message": {}}]}
        )
        == {}
    )


def test_openclaw_content_keys_redacted():
    """ruleset.v2: OpenClaw prompt/response/tool free text never rides the
    envelope. The keys are dropped with recorded entries."""
    payload = {
        "session_id": "sess-oc",
        "events": [
            _openclaw_event(
                "context.compiled",
                {
                    "prompt": "secret prompt text",
                    "systemPrompt": "you are an agent with these tools",
                    "imagesCount": 0,
                },
            ),
            _openclaw_event(
                "trace.artifacts",
                {
                    "assistantTexts": ["model reply"],
                    "toolMetas": [{"toolName": "exec", "meta": "rm -rf notes"}],
                    "messagingToolSentTexts": ["sent message"],
                    "messagesSnapshot": [{"role": "user"}],
                    "finalPromptText": "final prompt",
                    "finalStatus": "success",
                },
            ),
        ],
    }
    result = redact_payload_with_manifest(payload)
    events = result.payload["events"]
    assert "prompt" not in events[0]["data"]
    assert "systemPrompt" not in events[0]["data"]
    assert events[0]["data"]["imagesCount"] == 0
    for key in (
        "assistantTexts",
        "toolMetas",
        "messagingToolSentTexts",
        "messagesSnapshot",
        "finalPromptText",
    ):
        assert key not in events[1]["data"]
    assert events[1]["data"]["finalStatus"] == "success"
    dropped_paths = {e.path for e in result.entries if e.category == "dropped_key"}
    assert "events[0].data.prompt" in dropped_paths
    assert "events[1].data.assistantTexts" in dropped_paths
