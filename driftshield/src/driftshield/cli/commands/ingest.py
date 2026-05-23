"""Ingest command for DriftShield CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import typer
from rich.console import Console

from driftshield.cli.discovery import discover_sessions, resolve_session
from driftshield.cli.parsers import detect_parser


console = Console(force_terminal=True)

_VALID_SUBMISSION_TIERS = {"oss", "teams"}


@dataclass(frozen=True, slots=True)
class SourceConnectorMetadata:
    connector_id: str | None = None
    source_type: str | None = None
    display_name: str | None = None
    parser_name: str | None = None

    def as_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.connector_id is not None:
            payload["connector_id"] = self.connector_id
        if self.source_type is not None:
            payload["source_type"] = self.source_type
        if self.display_name is not None:
            payload["display_name"] = self.display_name
        if self.parser_name is not None:
            payload["parser_name"] = self.parser_name
        return payload


@dataclass(frozen=True, slots=True)
class SubmissionContext:
    submission_tier: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    workflow_reference: str | None = None
    project_reference: str | None = None
    source_connector: SourceConnectorMetadata | None = None
    signature_summary_json: str | None = None


def ingest(
    path: str | None = typer.Option(
        None,
        "--path",
        help="Session file path or session identifier to ingest.",
    ),
    project: bool = typer.Option(
        False,
        "--project",
        help="Ingest the latest discovered session for the current project.",
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Alias for ingesting the latest discovered session for the current project.",
    ),
    parser: str = typer.Option(
        "auto",
        "--parser",
        "-p",
        help="Parser to use (auto, claude_code, claude_desktop, codex_cli, codex_desktop, crewai, langchain, openclaw).",
    ),
    submission_tier: str = typer.Option(
        "oss",
        "--submission-tier",
        help="Remote submission tier (oss or teams).",
        envvar="DRIFTSHIELD_SUBMISSION_TIER",
    ),
    tenant_id: str | None = typer.Option(
        None,
        "--tenant-id",
        help="Claimed tenant identifier for Teams submissions.",
        envvar="DRIFTSHIELD_TENANT_ID",
    ),
    workspace_id: str | None = typer.Option(
        None,
        "--workspace-id",
        help="Claimed workspace identifier for Teams submissions.",
        envvar="DRIFTSHIELD_WORKSPACE_ID",
    ),
    workflow_reference: str | None = typer.Option(
        None,
        "--workflow-reference",
        help="Optional workflow identifier for the submission.",
        envvar="DRIFTSHIELD_WORKFLOW_REFERENCE",
    ),
    project_reference: str | None = typer.Option(
        None,
        "--project-reference",
        help="Optional project identifier for the submission.",
        envvar="DRIFTSHIELD_PROJECT_REFERENCE",
    ),
    source_connector_id: str | None = typer.Option(
        None,
        "--source-connector-id",
        help="Optional source connector identifier.",
        envvar="DRIFTSHIELD_SOURCE_CONNECTOR_ID",
    ),
    source_connector_type: str | None = typer.Option(
        None,
        "--source-connector-type",
        help="Optional source connector type.",
        envvar="DRIFTSHIELD_SOURCE_CONNECTOR_TYPE",
    ),
    source_connector_name: str | None = typer.Option(
        None,
        "--source-connector-name",
        help="Optional source connector display name.",
        envvar="DRIFTSHIELD_SOURCE_CONNECTOR_NAME",
    ),
    source_connector_parser: str | None = typer.Option(
        None,
        "--source-connector-parser",
        help="Optional source connector parser name.",
        envvar="DRIFTSHIELD_SOURCE_CONNECTOR_PARSER",
    ),
    include_analysis: bool = typer.Option(
        False,
        "--include-analysis",
        help=(
            "Run the local deterministic matcher and attach a signature_summary "
            "form field to the multipart upload. Off by default; no behavioural "
            "change vs the default ingest path when omitted."
        ),
    ),
) -> None:
    """Upload a transcript to the DriftShield ingest API."""
    selected = [bool(path), project, latest]
    if sum(selected) != 1:
        console.print("[red]Error:[/red] Choose exactly one of --path, --project, or --latest.")
        raise typer.Exit(1)

    file_path = _resolve_ingest_file(path=path, project=project or latest)

    effective_parser = parser
    if effective_parser == "auto":
        detected = detect_parser(file_path)
        if detected is None:
            console.print(
                f"[red]Error:[/red] Could not detect parser for '{file_path.name}'. Use --parser."
            )
            raise typer.Exit(1)
        effective_parser = detected

    api_url = os.environ.get("DRIFTSHIELD_API_URL", "http://localhost:8000")
    api_key = os.environ.get("DRIFTSHIELD_API_KEY") or os.environ.get("API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] DRIFTSHIELD_API_KEY (or API_KEY) is required.")
        raise typer.Exit(1)

    try:
        submission_context = build_submission_context(
            api_url=api_url,
            api_key=api_key,
            submission_tier=submission_tier,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_reference=workflow_reference,
            project_reference=project_reference,
            source_connector=SourceConnectorMetadata(
                connector_id=source_connector_id,
                source_type=source_connector_type,
                display_name=source_connector_name,
                parser_name=source_connector_parser,
            ),
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        console.print(f"[red]Error:[/red] Tenant resolution failed with HTTP {exc.code}: {detail}")
        raise typer.Exit(1) from exc
    except error.URLError as exc:
        console.print(f"[red]Error:[/red] Could not reach Teams auth-check endpoint: {exc.reason}")
        raise typer.Exit(1) from exc

    if include_analysis:
        try:
            from driftshield.cli._signature_summary import (
                build_signature_summary_from_session,
            )

            summary = build_signature_summary_from_session(file_path)
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[yellow]Warning:[/yellow] Could not derive signature_summary "
                f"({exc}). Ingest will proceed without it."
            )
            summary = None
        if summary is not None:
            submission_context = SubmissionContext(
                submission_tier=submission_context.submission_tier,
                tenant_id=submission_context.tenant_id,
                workspace_id=submission_context.workspace_id,
                workflow_reference=submission_context.workflow_reference,
                project_reference=submission_context.project_reference,
                source_connector=submission_context.source_connector,
                signature_summary_json=summary.model_dump_json(),
            )

    target_url = api_url.rstrip("/") + "/api/ingest"

    try:
        payload = post_ingest(
            target_url=target_url,
            api_key=api_key,
            file_path=file_path,
            parser=effective_parser,
            submission_context=submission_context,
        )
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        console.print(f"[red]Error:[/red] Ingest failed with HTTP {exc.code}: {detail}")
        raise typer.Exit(1) from exc
    except error.URLError as exc:
        console.print(f"[red]Error:[/red] Could not reach ingest API: {exc.reason}")
        raise typer.Exit(1) from exc

    status = payload.get("status", "unknown")
    session_id = payload.get("session_id", "unknown")
    total_events = payload.get("total_events", "?")
    flagged_events = payload.get("flagged_events", "?")

    if payload.get("deduplicated"):
        console.print(
            "[yellow]Transcript already ingested[/yellow] "
            f"(status={status}, session_id={session_id}, events={total_events}, flagged={flagged_events})."
        )
        return

    console.print(
        "[green]Ingested transcript[/green] "
        f"(status={status}, session_id={session_id}, events={total_events}, flagged={flagged_events})."
    )



def build_submission_context(
    *,
    api_url: str,
    api_key: str,
    submission_tier: str,
    tenant_id: str | None,
    workspace_id: str | None,
    workflow_reference: str | None,
    project_reference: str | None,
    source_connector: SourceConnectorMetadata,
) -> SubmissionContext:
    normalized_tier = submission_tier.strip().lower()
    if normalized_tier not in _VALID_SUBMISSION_TIERS:
        valid = ", ".join(sorted(_VALID_SUBMISSION_TIERS))
        raise ValueError(f"submission tier must be one of: {valid}")

    normalized_source_connector = _normalise_source_connector(source_connector)
    if normalized_tier == "oss":
        return SubmissionContext(
            submission_tier=normalized_tier,
            workflow_reference=_optional_string(workflow_reference),
            project_reference=_optional_string(project_reference),
            source_connector=normalized_source_connector,
        )

    normalized_tenant_id = _required_string(tenant_id, field_name="tenant_id")
    resolved = resolve_teams_submission_context(
        api_url=api_url,
        api_key=api_key,
        tenant_id=normalized_tenant_id,
        workspace_id=_optional_string(workspace_id),
    )
    resolved_tenant_id = _required_string(resolved.get("tenant_id"), field_name="tenant_id")
    resolved_workspace_id = _optional_string(resolved.get("workspace_id"))

    return SubmissionContext(
        submission_tier=normalized_tier,
        tenant_id=resolved_tenant_id,
        workspace_id=resolved_workspace_id,
        workflow_reference=_optional_string(workflow_reference),
        project_reference=_optional_string(project_reference),
        source_connector=normalized_source_connector,
    )


def _resolve_ingest_file(*, path: str | None, project: bool) -> Path:
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    if project:
        sessions = discover_sessions(Path.cwd(), claude_base)
        if not sessions:
            console.print("[red]Error:[/red] No sessions found for this project.")
            raise typer.Exit(1)
        return sessions[0].path

    assert path is not None
    resolved = resolve_session(path, Path.cwd(), claude_base)
    if resolved is None:
        direct = Path(path).expanduser().resolve()
        if direct.exists() and direct.is_file():
            resolved = direct
        else:
            console.print(f"[red]Error:[/red] Could not find session: {path}")
            raise typer.Exit(1)
    return resolved



def post_ingest(
    *,
    target_url: str,
    api_key: str,
    file_path: Path,
    parser: str,
    submission_context: SubmissionContext,
) -> dict[str, Any]:
    boundary = f"driftshield-{uuid.uuid4().hex}"
    body = _build_multipart_body(
        boundary=boundary,
        file_path=file_path,
        parser=parser,
        submission_context=submission_context,
    )
    req = request.Request(
        target_url,
        data=body,
        method="POST",
        headers={
            "X-API-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )

    with request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))



def resolve_teams_submission_context(
    *,
    api_url: str,
    api_key: str,
    tenant_id: str,
    workspace_id: str | None,
) -> dict[str, Any]:
    query_params = {"tenant_id": tenant_id}
    if workspace_id is not None:
        query_params["workspace_id"] = workspace_id
    auth_url = (
        os.environ.get("DRIFTSHIELD_TEAMS_AUTH_CHECK_URL")
        or api_url.rstrip("/") + "/v1/teams/auth-check"
    )
    req = request.Request(
        auth_url + "?" + parse.urlencode(query_params),
        method="GET",
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
        },
    )

    with request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Teams auth-check returned an invalid payload")
    return payload


def _build_multipart_body(
    *,
    boundary: str,
    file_path: Path,
    parser: str,
    submission_context: SubmissionContext,
) -> bytes:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    filename = file_path.name

    segments: list[bytes] = []
    _append_text_form_field(segments, boundary=boundary, name="format", value=parser)
    _append_text_form_field(
        segments,
        boundary=boundary,
        name="submission_tier",
        value=submission_context.submission_tier,
    )
    _append_optional_text_form_field(
        segments,
        boundary=boundary,
        name="tenant_id",
        value=submission_context.tenant_id,
    )
    _append_optional_text_form_field(
        segments,
        boundary=boundary,
        name="workspace_id",
        value=submission_context.workspace_id,
    )
    _append_optional_text_form_field(
        segments,
        boundary=boundary,
        name="workflow_reference",
        value=submission_context.workflow_reference,
    )
    _append_optional_text_form_field(
        segments,
        boundary=boundary,
        name="project_reference",
        value=submission_context.project_reference,
    )
    _append_optional_text_form_field(
        segments,
        boundary=boundary,
        name="signature_summary",
        value=submission_context.signature_summary_json,
    )
    if submission_context.source_connector is not None:
        source_connector_payload = submission_context.source_connector.as_payload()
        if source_connector_payload:
            _append_text_form_field(
                segments,
                boundary=boundary,
                name="source_connector_metadata",
                value=json.dumps(source_connector_payload, sort_keys=True),
            )
    segments.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(segments)


def _append_text_form_field(segments: list[bytes], *, boundary: str, name: str, value: str) -> None:
    segments.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
            value.encode("utf-8"),
            b"\r\n",
        ]
    )


def _append_optional_text_form_field(
    segments: list[bytes],
    *,
    boundary: str,
    name: str,
    value: str | None,
) -> None:
    if value is None:
        return
    _append_text_form_field(segments, boundary=boundary, name=name, value=value)


def _normalise_source_connector(
    source_connector: SourceConnectorMetadata,
) -> SourceConnectorMetadata | None:
    connector_id = _optional_string(source_connector.connector_id)
    source_type = _optional_string(source_connector.source_type)
    display_name = _optional_string(source_connector.display_name)
    parser_name = _optional_string(source_connector.parser_name)
    if all(value is None for value in (connector_id, source_type, display_name, parser_name)):
        return None
    return SourceConnectorMetadata(
        connector_id=connector_id,
        source_type=source_type,
        display_name=display_name,
        parser_name=parser_name,
    )


def _required_string(value: object, *, field_name: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise ValueError(f"{field_name} is required for Teams submissions")
    return normalized


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected string value")
    normalized = value.strip()
    return normalized or None
