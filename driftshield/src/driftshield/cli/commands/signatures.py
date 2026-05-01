"""CLI commands for pulling community signature packs."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.signatures.distribution import (
    DEFAULT_COMMUNITY_REPOSITORY,
    build_github_raw_manifest_url,
    describe_pack_source,
    install_community_pack,
)

console = Console(force_terminal=True)
app = typer.Typer(help="Manage community signature pack distribution.")


def _validate_repository(repository: str) -> str:
    parts = [part.strip() for part in repository.split("/")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("--repository must use the exact format owner/repo")
    return f"{parts[0]}/{parts[1]}"


@app.command("pull")
def pull_signature_pack(
    pack_name: str = typer.Argument(..., help="Community pack name without the .json suffix."),
    ref: str | None = typer.Option(
        None,
        "--ref",
        help="Git ref or tag to pull from when using the default GitHub source.",
    ),
    repository: str = typer.Option(
        DEFAULT_COMMUNITY_REPOSITORY,
        "--repository",
        help="GitHub repository that publishes the raw community pack manifest.",
    ),
    source_url: str | None = typer.Option(
        None,
        "--url",
        help="Explicit distribution-manifest or legacy pack URL. Overrides --repository/--ref when supplied.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Write the validated pack manifest to this exact path instead of the default install cache.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Fetch, validate, and install a versioned community signature pack manifest."""
    if source_url is None and ref is None:
        console.print("[red]Error:[/red] --ref is required unless --url is provided.")
        raise typer.Exit(1)

    try:
        resolved_source_url = source_url or build_github_raw_manifest_url(
            repository=_validate_repository(repository),
            ref=ref or "",
        )
        pulled = install_community_pack(
            source_url=resolved_source_url,
            destination=output,
            pack_name_hint=pack_name,
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] Could not pull pack: {exc}")
        raise typer.Exit(1) from exc

    payload = {
        "pack_name": pulled.manifest.metadata.name,
        "pack_version": pulled.manifest.metadata.version,
        "schema_version": pulled.manifest.schema_version,
        "source_url": describe_pack_source(pulled.source_url),
        "manifest_url": describe_pack_source(pulled.manifest_url) if pulled.manifest_url else None,
        "installed_path": str(pulled.installed_path),
        "signature_count": len(pulled.manifest.signatures),
        "family_coverage": list(pulled.manifest.family_coverage),
        "used_cached_pack": pulled.used_cached_pack,
    }
    if json_output:
        typer.echo(json.dumps(payload))
        return

    console.print(
        f"[green]{'Using cached community pack' if pulled.used_cached_pack else 'Pulled community pack'}[/green] "
        f"{payload['pack_name']}@{payload['pack_version']} "
        f"(schema {payload['schema_version']}, signatures={payload['signature_count']})."
    )
    if payload["manifest_url"]:
        console.print(f"Manifest: {payload['manifest_url']}")
    console.print(f"Source: {payload['source_url']}")
    console.print(f"Installed: {payload['installed_path']}")
