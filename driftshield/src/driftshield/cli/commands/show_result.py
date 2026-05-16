"""Show-result command: read the OSS-safe result triple for a submission."""

from __future__ import annotations

import json
from urllib import error, request

import typer
from rich.console import Console

from driftshield.telemetry import TelemetryService


console = Console(force_terminal=True)


def show_result(
    submission_id: str = typer.Argument(..., help="Submission ID returned by `telemetry submit-session`."),
    intake_url: str | None = typer.Option(
        None,
        "--intake-url",
        help="Override the intake URL. Defaults to the value persisted by `telemetry remote-enable`.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print the raw JSON response."),
) -> None:
    """Fetch the OSS-safe result triple for a submission from the configured intake URL."""
    base_url = intake_url
    if base_url is None:
        config = TelemetryService().load_config()
        base_url = config.remote_intake_url
    if not base_url:
        console.print(
            "[red]Error:[/red] No intake URL configured. "
            "Run `driftshield telemetry remote-enable --intake-url URL` first, "
            "or pass --intake-url."
        )
        raise typer.Exit(1)

    submission_url = _derive_submission_url(base_url, submission_id)
    req = request.Request(
        submission_url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        if exc.code == 404:
            console.print(f"[red]Error:[/red] Submission not found: {submission_id}")
        else:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            console.print(f"[red]Error:[/red] intake HTTP {exc.code}: {detail}")
        raise typer.Exit(1) from exc
    except error.URLError as exc:
        console.print(f"[red]Error:[/red] intake unreachable: {exc.reason}")
        raise typer.Exit(1) from exc

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error:[/red] intake returned non-JSON body: {raw!r}")
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(body))
        return

    console.print(f"Submission: {body.get('submission_id')}")
    console.print(f"Status: {body.get('processing_status')}")
    signature_label = body.get("signature_label")
    signature_family = body.get("signature_family")
    if signature_label is None:
        console.print("Signature: (not yet matched)")
    else:
        family_display = signature_family if signature_family is not None else "unknown"
        console.print(f"Signature: {signature_label} ({family_display})")
    confidence_band = body.get("confidence_band")
    if confidence_band is None:
        console.print("Confidence: (not yet evaluated)")
    else:
        console.print(f"Confidence: {confidence_band}")


def _derive_submission_url(base_url: str, submission_id: str) -> str:
    """Derive the GET /v1/oss/submissions/{submission_id} URL from the configured intake URL.

    The intake URL is expected to end with /v1/intake or /v1/oss/submissions. Strip the suffix
    (so we don't double-append), then re-append the OSS-result path. If neither suffix is
    present, fall back to appending /v1/oss/submissions/{id} to the base.
    """
    trimmed = base_url.rstrip("/")
    for suffix in ("/v1/intake", "/v1/oss/submissions"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            break
    return f"{trimmed}/v1/oss/submissions/{submission_id}"
