"""CLI commands for pulling community signature packs."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from driftshield.signatures.distribution import (
    DEFAULT_COMMUNITY_REPOSITORY,
    build_github_raw_pack_url,
    describe_pack_source,
    install_community_pack,
)

console = Console(force_terminal=True)
app = typer.Typer(help="Manage community signature pack distribution.")


@app.command("pull")
def pull_signature_pack(
    pack_name: str = typer.Argument(..., help="Community pack name without the .json suffix."),
    ref: str = typer.Option(
        ..., "--ref", help="Git ref or tag to pull from when using the default GitHub source."
    ),
    repository: str = typer.Option(
        DEFAULT_COMMUNITY_REPOSITORY,
        "--repository",
        help="GitHub repository that publishes the raw community pack manifest.",
    ),
    source_url: str | None = typer.Option(
        None,
        "--url",
        help="Explicit manifest URL. Overrides --repository/--ref when supplied.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Write the validated pack manifest to this exact path instead of the default install cache.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Fetch, validate, and install a versioned community signature pack manifest."""
    resolved_source_url = source_url or build_github_raw_pack_url(
        repository=repository,
        ref=ref,
        pack_name=pack_name,
    )

    try:
        pulled = install_community_pack(
            source_url=resolved_source_url,
            destination=output,
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] Could not pull pack: {exc}")
        raise typer.Exit(1) from exc

    payload = {
        "pack_name": pulled.manifest.metadata.name,
        "pack_version": pulled.manifest.metadata.version,
        "schema_version": pulled.manifest.schema_version,
        "source_url": describe_pack_source(pulled.source_url),
        "installed_path": str(pulled.installed_path),
        "signature_count": len(pulled.manifest.signatures),
        "family_coverage": list(pulled.manifest.family_coverage),
    }
    if json_output:
        typer.echo(json.dumps(payload))
        return

    console.print(
        "[green]Pulled community pack[/green] "
        f"{payload['pack_name']}@{payload['pack_version']} "
        f"(schema {payload['schema_version']}, signatures={payload['signature_count']})."
    )
    console.print(f"Source: {payload['source_url']}")
    console.print(f"Installed: {payload['installed_path']}")
