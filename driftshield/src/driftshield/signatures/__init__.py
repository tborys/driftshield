"""Public extension seam for third-party and private signature packs.

This module is intentionally interface-only. It does not bundle signature
packs, recurrence logic, or matching behavior into the OSS package.

Example:
    from collections.abc import Iterable

    from driftshield.signatures import (
        SignatureDefinition,
        SignaturePackMetadata,
        SignatureProvider,
    )

    class CommunityPack:
        def describe(self) -> SignaturePackMetadata:
            return SignaturePackMetadata(
                name="community-general",
                version="1.0.0",
                description="General-purpose failure signatures.",
            )

        def iter_signatures(self) -> Iterable[SignatureDefinition]:
            yield SignatureDefinition(
                signature_id="SIG-COMM-001",
                title="Coverage Gap",
                summary="Required evidence is skipped before completion.",
                failure_shape="collect->branch->skip->complete",
            )
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SignatureSeverity(StrEnum):
    """Severity hint supplied by an external signature pack."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SignatureDefinition:
    """Portable metadata for a signature supplied by an external pack."""

    signature_id: str
    title: str
    summary: str
    failure_shape: str
    severity: SignatureSeverity = SignatureSeverity.MEDIUM
    lexical_markers: Sequence[str] = ()
    temporal_constraints: Sequence[str] = ()
    tags: Sequence[str] = ()

    def __post_init__(self) -> None:
        if not self.signature_id:
            raise ValueError("signature_id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.summary:
            raise ValueError("summary is required")
        if not self.failure_shape:
            raise ValueError("failure_shape is required")

        object.__setattr__(self, "lexical_markers", _as_tuple(self.lexical_markers))
        object.__setattr__(self, "temporal_constraints", _as_tuple(self.temporal_constraints))
        object.__setattr__(self, "tags", _as_tuple(self.tags))


@dataclass(frozen=True, slots=True)
class SignaturePackMetadata:
    """Identity metadata for a provider-managed signature pack."""

    name: str
    version: str
    description: str = ""
    homepage_url: str | None = None
    documentation_url: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name is required")
        if not self.version:
            raise ValueError("version is required")


@runtime_checkable
class SignatureProvider(Protocol):
    """Public contract for packages that expose signature definitions."""

    def describe(self) -> SignaturePackMetadata:
        """Return stable metadata describing the provided signature pack."""
        ...

    def iter_signatures(self) -> Iterable[SignatureDefinition]:
        """Yield signature definitions supplied by this pack."""
        ...


def _as_tuple(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(values)


__all__ = [
    "SignatureDefinition",
    "SignaturePackMetadata",
    "SignatureProvider",
    "SignatureSeverity",
]
