"""Parser protocol for log ingestion."""

from typing import Protocol

from driftshield.core.models import CanonicalEvent


class TranscriptParser(Protocol):
    """Protocol for parsing agent transcripts into CanonicalEvents."""

    # Records the last parse() could not use, by reason. ``None`` means this
    # parser does not count skipped records (not "none were skipped").
    @property
    def skipped_records_by_reason(self) -> dict[str, int] | None:
        """Skipped records by reason, or ``None`` when the parser does not count."""
        ...

    @property
    def skipped_record_count(self) -> int | None:
        """Total skipped records, or ``None`` when the parser does not count."""
        ...

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


class UncountedSkips:
    """Mixin for parsers that do not count skipped records."""

    @property
    def skipped_records_by_reason(self) -> dict[str, int] | None:
        return None

    @property
    def skipped_record_count(self) -> int | None:
        return None
