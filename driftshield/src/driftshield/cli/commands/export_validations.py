"""CLI command to export analyst validations into JSONL training dataset."""

from pathlib import Path

import typer

from driftshield.db.engine import get_engine, get_session_factory
from driftshield.db.models import Base
from driftshield.db.validation_service import ValidationService


def export_validations(
    output: Path = typer.Option(..., "--output", "-o", help="Output JSONL path"),
) -> None:
    """Export shareable analyst validation records as training dataset JSONL."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    SessionLocal = get_session_factory(engine)

    with SessionLocal() as db:
        service = ValidationService(db)
        count = service.export_training_dataset_jsonl(output)

    typer.echo(f"Exported {count} validation record(s) to {output}")
