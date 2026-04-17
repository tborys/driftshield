from pathlib import Path

import typer


def generate_fixtures(
    output_dir: Path = typer.Option(
        Path("docker/fixtures"), "--output-dir", "-o", help="Output directory"
    ),
    include_clean: bool = typer.Option(
        True,
        "--include-clean/--no-include-clean",
        help="Include clean session fixture",
    ),
) -> None:
    """Generate deterministic JSONL transcript fixtures for demos/testing."""
    from driftshield.fixtures.transcript_generator import (
        ScenarioTranscriptGenerator,
        default_scenario_registry,
    )

    generator = ScenarioTranscriptGenerator(default_scenario_registry())
    written = generator.generate(output_dir=output_dir, include_clean=include_clean)

    typer.echo(f"Generated {len(written)} fixture file(s)")
    for path in written:
        typer.echo(f"- {path}")
