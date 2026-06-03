"""Tests for the presigned-S3 large-upload client (remote_upload)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from driftshield.remote_submission import RemoteSubmissionError
from driftshield.remote_upload import (
    OssUploadConfig,
    TeamsUploadConfig,
    derive_intake_base_url,
    submit_oss_via_presigned_upload,
    submit_teams_via_presigned_upload,
)


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _routing_opener(calls: list[dict[str, Any]]):
    """Opener that records each call and routes by URL: presign → S3 → finalise."""

    def opener(req: Any) -> _FakeResponse:
        url = req.full_url
        calls.append(
            {"url": url, "method": req.get_method(), "headers": dict(req.headers)}
        )
        if url.endswith("/uploads/presign"):
            return _FakeResponse(
                json.dumps(
                    {
                        "upload_id": "up_1",
                        "url": "https://s3.example/bucket",
                        "fields": {"key": "uploads/raw/up_1", "Content-Type": "application/json"},
                        "max_bytes": 50 * 1024 * 1024,
                    }
                ).encode("utf-8")
            )
        if url.endswith("/uploads/finalise"):
            return _FakeResponse(
                json.dumps(
                    {"submission_id": "sub_1", "processing_status": "received"}
                ).encode("utf-8")
            )
        # The multipart POST direct to S3.
        return _FakeResponse(b"")

    return opener


def test_derive_intake_base_url_strips_known_suffixes() -> None:
    assert derive_intake_base_url("https://api.example/v1/oss/submissions") == "https://api.example"
    assert derive_intake_base_url("https://api.example/v1/intake") == "https://api.example"
    assert derive_intake_base_url("https://api.example/") == "https://api.example"


def test_oss_upload_does_presign_then_s3_then_finalise() -> None:
    calls: list[dict[str, Any]] = []
    result = submit_oss_via_presigned_upload(
        config=OssUploadConfig(intake_url="https://api.example/v1/oss/submissions"),
        payload={"session_id": "sess-1", "signals": ["retry_loop"]},
        workflow_reference="default",
        file_name="s.jsonl",
        opener=_routing_opener(calls),
    )
    assert result.response.submission_id == "sub_1"
    # Three calls in order: presign, S3 multipart, finalise.
    assert calls[0]["url"].endswith("/v1/oss/uploads/presign")
    assert calls[1]["url"] == "https://s3.example/bucket"
    assert calls[2]["url"].endswith("/v1/oss/uploads/finalise")
    # OSS lane sends no API key on any hop.
    for call in calls:
        assert "X-api-key" not in call["headers"]
        assert "X-Api-Key" not in call["headers"]


def test_teams_upload_sends_api_key_on_presign_and_finalise() -> None:
    calls: list[dict[str, Any]] = []
    result = submit_teams_via_presigned_upload(
        config=TeamsUploadConfig(
            intake_url="https://api.example/v1/intake", api_key="ds_teams_key"
        ),
        payload={"session_id": "sess-1", "signals": ["retry_loop"]},
        workflow_reference="default",
        file_name="s.jsonl",
        opener=_routing_opener(calls),
    )
    assert result.response.submission_id == "sub_1"
    assert calls[0]["url"].endswith("/v1/teams/uploads/presign")
    assert calls[2]["url"].endswith("/v1/teams/uploads/finalise")
    # The API key rides the presign + finalise hops (header-normalised key).
    presign_headers = {k.lower(): v for k, v in calls[0]["headers"].items()}
    finalise_headers = {k.lower(): v for k, v in calls[2]["headers"].items()}
    assert presign_headers["x-api-key"] == "ds_teams_key"
    assert finalise_headers["x-api-key"] == "ds_teams_key"


def test_malformed_presign_response_raises() -> None:
    def opener(req: Any) -> _FakeResponse:
        return _FakeResponse(json.dumps({"oops": True}).encode("utf-8"))

    with pytest.raises(RemoteSubmissionError):
        submit_oss_via_presigned_upload(
            config=OssUploadConfig(intake_url="https://api.example/v1/oss/submissions"),
            payload={"session_id": "sess-1"},
            workflow_reference="default",
            file_name="s.jsonl",
            opener=opener,
        )


def test_provenance_fields_ride_the_finalise_body() -> None:
    """Reviewer finding: the presigned lane must not drop provenance."""
    finalise_bodies: list[dict[str, Any]] = []

    def opener(req: Any) -> _FakeResponse:
        url = req.full_url
        if url.endswith("/uploads/presign"):
            return _FakeResponse(
                json.dumps(
                    {
                        "upload_id": "up_1",
                        "url": "https://s3.example/bucket",
                        "fields": {"key": "uploads/raw/up_1"},
                        "max_bytes": 50 * 1024 * 1024,
                    }
                ).encode("utf-8")
            )
        if url.endswith("/uploads/finalise"):
            finalise_bodies.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse(
                json.dumps(
                    {"submission_id": "sub_1", "processing_status": "received"}
                ).encode("utf-8")
            )
        return _FakeResponse(b"")

    submit_teams_via_presigned_upload(
        config=TeamsUploadConfig(
            intake_url="https://api.example/v1/intake", api_key="k"
        ),
        payload={"session_id": "sess-1"},
        workflow_reference="wf-triage",
        file_name="s.jsonl",
        provenance={
            "source_session_id": "sess-prov",
            "project_reference": "proj-ops",
            "agent_id": "agent-x",
            "model_name": "claude",
        },
        opener=opener,
    )
    body = finalise_bodies[0]
    assert body["source_session_id"] == "sess-prov"
    assert body["project_reference"] == "proj-ops"
    assert body["agent_id"] == "agent-x"
    assert body["model_name"] == "claude"
    assert body["workflow_reference"] == "wf-triage"
