"""Unit tests for the D19 unauthenticated OSS submission module."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib import error

import pytest

from driftshield.intake_contract import (
    REDACTION_MANIFEST_VERSION,
    REQUIRED_REDACTION_FIELDS,
    SUPPORTED_CONTRACT_VERSION,
    OssSubmissionRequest,
)
from driftshield.remote_submission import (
    OssRemoteSubmissionConfig,
    RemoteSubmissionError,
    build_oss_submission_request,
    post_oss_submission,
    redact_payload,
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


def test_build_oss_submission_request_phase3f_v1_shape():
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
    assert request.envelope_contract_version == SUPPORTED_CONTRACT_VERSION

    envelope = request.envelope
    assert envelope.schema_version == SUPPORTED_CONTRACT_VERSION
    assert envelope.source_session_id == "sess-1"
    assert "prompts" not in envelope.payload
    assert "responses" not in envelope.payload
    assert "user_identifiers" not in envelope.payload
    assert envelope.payload["session_id"] == "sess-1"
    assert envelope.payload["metadata"] == {"foo": "bar"}

    assert envelope.redaction_manifest.manifest_version == REDACTION_MANIFEST_VERSION
    assert envelope.redaction_manifest.redaction_applied is True
    assert set(envelope.redaction_manifest.redacted_fields) == REQUIRED_REDACTION_FIELDS


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
    def __init__(self, body: bytes) -> None:
        self._body = body

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
            json.dumps({"submission_id": "sub_abc", "processing_status": "received"}).encode("utf-8")
        )

    request = build_oss_submission_request(
        source_session_id="sess-1",
        payload={"session_id": "sess-1"},
    )

    response = post_oss_submission(config=_config(), submission=request, opener=fake_opener)

    assert response.submission_id == "sub_abc"
    assert response.processing_status == "received"
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
