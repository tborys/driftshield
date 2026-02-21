"""DriftShield CLI entry point."""

import typer

from driftshield import __version__
from driftshield.cli.commands.analyze import analyze
from driftshield.cli.commands.list import list_sessions
from driftshield.cli.commands.inspect import inspect
from driftshield.cli.commands.report import report_command
from driftshield.cli.commands.export_validations import export_validations

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)

# Register commands
app.command()(analyze)
app.command(name="list")(list_sessions)
app.command()(inspect)
app.command(name="report")(report_command)
app.command(name="export-validations")(export_validations)


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
