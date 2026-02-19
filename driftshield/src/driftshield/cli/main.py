"""DriftShield CLI entry point."""

import typer

from driftshield import __version__

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        print(f"driftshield {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DriftShield - AI Decision Forensics CLI."""
    pass
