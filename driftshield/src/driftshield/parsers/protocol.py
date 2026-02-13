"""Parser protocol for log ingestion."""

from typing import Protocol

from driftshield.core.models import CanonicalEvent


class TranscriptParser(Protocol):
    """Protocol for parsing agent transcripts into CanonicalEvents."""

    def parse(self, content: str) -> list[CanonicalEvent]:
        """Parse raw transcript content into canonical events."""
        ...

    def parse_file(self, file_path: str) -> list[CanonicalEvent]:
        """Parse transcript from file path."""
        ...

    @property
    def source_type(self) -> str:
        """Return identifier for this parser type (e.g., 'claude_code')."""
        ...
