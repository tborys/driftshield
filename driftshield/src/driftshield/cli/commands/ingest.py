"""Ingest command for DriftShield CLI."""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

import typer
from rich.console import Console

from driftshield.cli.discovery import discover_sessions, resolve_session
from driftshield.cli.parsers import detect_parser


console = Console()


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
        help="Parser to use (auto, claude_code).",
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

    target_url = api_url.rstrip("/") + "/api/ingest"

    try:
        payload = post_ingest(
            target_url=target_url,
            api_key=api_key,
            file_path=file_path,
            parser=effective_parser,
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



def post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str) -> dict[str, Any]:
    boundary = f"driftshield-{uuid.uuid4().hex}"
    body = _build_multipart_body(boundary=boundary, file_path=file_path, parser=parser)
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



def _build_multipart_body(*, boundary: str, file_path: Path, parser: str) -> bytes:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    filename = file_path.name

    segments: list[bytes] = [
        f"--{boundary}\r\n".encode("utf-8"),
        b'Content-Disposition: form-data; name="format"\r\n\r\n',
        parser.encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        ).encode("utf-8"),
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(segments)
