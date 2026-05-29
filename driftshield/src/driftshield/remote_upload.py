"""Presigned-S3 upload client for large OSS session submissions.

Some session transcripts are large (tens of MB). The inline
``POST /v1/oss/submissions`` lane cannot carry them: the request body is
bounded by the upload transport. The presigned-S3 lane lifts that limit —
the client requests a presigned upload, PUTs the (locally-redacted)
transcript straight to object storage, then finalises by id. The server
reads it back, runs its own redaction pass, and persists.

This module is intentionally stdlib-only (``urllib`` + a small multipart
encoder) so the OSS distribution does not gain an HTTP dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request

from driftshield.intake_contract import IntakeSubmissionResponse
from driftshield.remote_submission import (
    SERVER_CONTRACT_VERSION_HEADER,
    OssSubmissionResult,
    RemoteSubmissionError,
)


# Payloads at or below this size go inline through POST /v1/oss/submissions
# (the existing small-file lane, unchanged). Larger payloads route through
# the presigned-S3 lane. 200 KB keeps a wide margin under the inline
# envelope cap while sending anything substantial via S3.
INLINE_PAYLOAD_THRESHOLD_BYTES = 200 * 1024

_OSS_SUBMIT_SUFFIXES = ("/v1/intake", "/v1/oss/submissions")
_PRESIGN_PATH = "/v1/oss/uploads/presign"
_FINALISE_PATH = "/v1/oss/uploads/finalise"
_TEAMS_PRESIGN_PATH = "/v1/teams/uploads/presign"
_TEAMS_FINALISE_PATH = "/v1/teams/uploads/finalise"


def derive_intake_base_url(intake_url: str) -> str:
    """Strip the known submit suffix from a configured intake URL.

    The configured ``remote_intake_url`` ends with ``/v1/intake`` or
    ``/v1/oss/submissions``; strip it so the presign + finalise paths can
    be appended to the same host without double-pathing.
    """
    trimmed = intake_url.rstrip("/")
    for suffix in _OSS_SUBMIT_SUFFIXES:
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
    return trimmed


def _post_json(
    url: str,
    body: dict[str, Any],
    *,
    api_key: str | None = None,
    opener: Any = None,
) -> dict[str, Any]:
    encoded = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    req = request.Request(url, data=encoded, method="POST", headers=headers)
    urlopen = opener or request.urlopen
    try:
        with urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            contract_version = resp.headers.get(SERVER_CONTRACT_VERSION_HEADER)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RemoteSubmissionError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RemoteSubmissionError(f"unreachable: {exc.reason}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RemoteSubmissionError(f"non-JSON body: {raw!r}") from exc
    if not isinstance(decoded, dict):
        raise RemoteSubmissionError(f"expected a JSON object, got: {raw!r}")
    result: dict[str, Any] = decoded
    result["_contract_version"] = contract_version
    return result


def _encode_multipart(
    fields: dict[str, str], *, file_field: str, file_name: str, file_bytes: bytes
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body for a presigned-POST upload.

    The presigned-POST policy fields must precede the file part. Returns
    the encoded body and the ``Content-Type`` header value (with boundary).
    """
    boundary = f"----driftshield{os.urandom(16).hex()}"
    crlf = b"\r\n"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"'.encode()
    )
    parts.append(b"Content-Type: application/octet-stream")
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _post_multipart(url: str, body: bytes, content_type: str, *, opener: Any = None) -> None:
    req = request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
    urlopen = opener or request.urlopen
    try:
        with urlopen(req):
            return
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RemoteSubmissionError(f"storage upload HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RemoteSubmissionError(f"storage unreachable: {exc.reason}") from exc


@dataclass(frozen=True, slots=True)
class OssUploadConfig:
    """Config for the presigned-S3 OSS (unauthenticated) upload lane."""

    intake_url: str


@dataclass(frozen=True, slots=True)
class TeamsUploadConfig:
    """Config for the presigned-S3 Teams (API-key) upload lane."""

    intake_url: str
    api_key: str


def _submit_via_presigned_upload(
    *,
    base: str,
    presign_path: str,
    finalise_path: str,
    payload: dict[str, Any],
    workflow_reference: str | None,
    file_name: str,
    mode: str,
    api_key: str | None,
    provenance: dict[str, Any] | None,
    opener: Any,
) -> OssSubmissionResult:
    """Shared presign → POST-to-S3 → finalise flow for both lanes.

    1. Ask the server for a presigned POST.
    2. POST the locally-redacted payload straight to S3.
    3. Finalise by ``upload_id``; the server reads it back, runs its own
       redaction pass + backstop, and persists.

    ``payload`` is already redacted by the local builder; the server's
    re-redaction is idempotent on clean content and the backstop is the
    final net. The payload is NOT wrapped in the size-capped
    :class:`SubmissionEnvelope` model here — large transcripts exceed that
    cap by design, which is why they take this lane.
    """
    content_type = "application/json"

    presign = _post_json(
        f"{base}{presign_path}",
        {"content_type": content_type},
        api_key=api_key,
        opener=opener,
    )
    upload_id = presign.get("upload_id")
    url = presign.get("url")
    presign_fields = presign.get("fields")
    if (
        not isinstance(upload_id, str)
        or not isinstance(url, str)
        or not isinstance(presign_fields, dict)
    ):
        raise RemoteSubmissionError(f"malformed presign response: {presign!r}")

    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    body, multipart_content_type = _encode_multipart(
        {str(k): str(v) for k, v in presign_fields.items()},
        file_field="file",
        file_name=file_name,
        file_bytes=payload_bytes,
    )
    _post_multipart(url, body, multipart_content_type, opener=opener)

    finalise_body: dict[str, Any] = {
        "upload_id": upload_id,
        "mode": mode,
        "content_type": content_type,
    }
    if mode == "file":
        finalise_body["file_name"] = file_name
    if workflow_reference:
        finalise_body["workflow_reference"] = workflow_reference
    # Carry the provenance surface (source_session_id, project_reference,
    # source_report_id, agent_id, model_name, model_version,
    # signature_summary) so the presigned lane is not lossier than inline.
    if provenance:
        finalise_body.update(provenance)

    decoded = _post_json(
        f"{base}{finalise_path}", finalise_body, api_key=api_key, opener=opener
    )
    contract_version = decoded.pop("_contract_version", None)
    response = IntakeSubmissionResponse.model_validate(decoded)
    return OssSubmissionResult(
        response=response,
        server_contract_version=contract_version,
    )


def submit_oss_via_presigned_upload(
    *,
    config: OssUploadConfig,
    payload: dict[str, Any],
    workflow_reference: str | None,
    file_name: str,
    mode: str = "file",
    provenance: dict[str, Any] | None = None,
    opener: Any = None,
) -> OssSubmissionResult:
    """Upload a large OSS (unauthenticated) session via presigned S3."""
    return _submit_via_presigned_upload(
        base=derive_intake_base_url(config.intake_url),
        presign_path=_PRESIGN_PATH,
        finalise_path=_FINALISE_PATH,
        payload=payload,
        workflow_reference=workflow_reference,
        file_name=file_name,
        mode=mode,
        api_key=None,
        provenance=provenance,
        opener=opener,
    )


def submit_teams_via_presigned_upload(
    *,
    config: TeamsUploadConfig,
    payload: dict[str, Any],
    workflow_reference: str | None,
    file_name: str,
    mode: str = "file",
    provenance: dict[str, Any] | None = None,
    opener: Any = None,
) -> OssSubmissionResult:
    """Upload a large Teams (API-key) session via presigned S3."""
    return _submit_via_presigned_upload(
        base=derive_intake_base_url(config.intake_url),
        presign_path=_TEAMS_PRESIGN_PATH,
        finalise_path=_TEAMS_FINALISE_PATH,
        payload=payload,
        workflow_reference=workflow_reference,
        file_name=file_name,
        mode=mode,
        api_key=config.api_key,
        provenance=provenance,
        opener=opener,
    )


__all__ = [
    "INLINE_PAYLOAD_THRESHOLD_BYTES",
    "OssUploadConfig",
    "TeamsUploadConfig",
    "derive_intake_base_url",
    "submit_oss_via_presigned_upload",
    "submit_teams_via_presigned_upload",
]
