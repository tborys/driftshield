"""List command for DriftShield CLI."""

import os
from pathlib import Path

import typer
from rich.console import Console

from driftshield.cli.discovery import discover_sessions, get_claude_projects_dir


console = Console()


def list_sessions(
    project: bool = typer.Option(
        False,
        "--project",
        help="List sessions for current project.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
) -> None:
    """List available sessions."""
    if not project:
        console.print(
            "[yellow]Hint:[/yellow] Use --project to list sessions for current directory."
        )
        raise typer.Exit(0)

    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    project_dir = Path.cwd()
    sessions = discover_sessions(project_dir, claude_base)

    if not sessions:
        console.print("No sessions found for this project.")
        console.print(f"[dim]Looking in: {get_claude_projects_dir(claude_base)}[/dim]")
        raise typer.Exit(0)

    if json_output:
        import json
        data = [
            {
                "index": i + 1,
                "session_id": s.session_id,
                "path": str(s.path),
                "modified_at": s.modified_at.isoformat(),
                "size_bytes": s.size_bytes,
            }
            for i, s in enumerate(sessions)
        ]
        console.print(json.dumps(data, indent=2))
    else:
        console.print(f"\nSessions for: [bold]{project_dir.name}[/bold]")
        console.print("\u2500" * 40)

        for i, session in enumerate(sessions, 1):
            try:
                event_count = sum(1 for _ in session.path.open())
            except Exception:
                event_count = "?"

            console.print(
                f"  {i}. {session.session_id}  "
                f"[dim]({session.age_description}, {event_count} lines)[/dim]"
            )

        console.print()
        console.print("[dim]Use: driftshield analyze <session-id>[/dim]")
