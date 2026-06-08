"""Tier-aware visibility enforcement for the canonical analysed-run payload.

The canonical analysis blob carries fields at different disclosure tiers. The OSS
runtime renders only ``oss``-class fields; richer tiers expose more. This module is
the single place that decides which field belongs to which tier, so the raw dict
can never bypass the boundary on its way to an API response, a report, or the CLI.

Every field emitted under the ``qualification``, ``provenance_environment``, and
``delta_records`` blocks MUST appear in both ``VISIBILITY_REGISTRY`` and the matching
``KNOWN_*`` set. A new field added without a class is caught by the build-side
completeness test, not shipped silently.
"""

from __future__ import annotations

from typing import Any

# Disclosure tiers, lowest to highest. A consumer at a given tier sees its own
# fields plus every lower tier.
_TIER_RANK: dict[str, int] = {
    "oss": 0,
    "teams": 1,
    "enterprise": 2,
    "internal_only": 3,
}

_DEFAULT_TIER = "oss"


# Dot-path -> minimum tier required to see the field.
# ``block.field`` addresses a field inside a dict block.
# ``delta_records.[].field`` addresses a field inside each delta record.
VISIBILITY_REGISTRY: dict[str, str] = {
    # qualification block
    "qualification.qualification_state": "oss",
    "qualification.qualification_reasons": "teams",
    "qualification.qualified_at": "teams",
    "qualification.classifiability_inputs": "teams",
    "qualification.qualification_schema_version": "teams",
    "qualification.qualification_policy_version": "internal_only",
    # nested classifiability_inputs children (registered individually so a future
    # nested field cannot ride the parent object's class unclassified)
    "qualification.classifiability_inputs.extraction_quality_band": "teams",
    "qualification.classifiability_inputs.coverage_ratio": "teams",
    "qualification.classifiability_inputs.event_count": "teams",
    "qualification.classifiability_inputs.has_expected_actual_delta": "teams",
    "qualification.classifiability_inputs.ambiguity_count": "teams",
    # provenance + environment block
    "provenance_environment.provenance_confidence": "teams",
    "provenance_environment.environment_class": "oss",
    "provenance_environment.environment_source": "teams",
    # delta records (per-field; the whole list is oss-visible)
    "delta_records": "oss",
    "delta_records.[].delta_type": "oss",
    "delta_records.[].delta_severity": "oss",
    "delta_records.[].expected_ref": "oss",
    "delta_records.[].actual_ref": "oss",
    "delta_records.[].delta_summary": "oss",
    "delta_records.[].delta_confidence": "oss",
}

# Source-of-truth field sets per block. The build-side completeness test asserts
# that the actually emitted keys equal these sets.
KNOWN_QUALIFICATION_FIELDS: frozenset[str] = frozenset(
    {
        "qualification_state",
        "qualification_reasons",
        "qualified_at",
        "classifiability_inputs",
        "qualification_schema_version",
        "qualification_policy_version",
    }
)
KNOWN_PROVENANCE_ENV_FIELDS: frozenset[str] = frozenset(
    {
        "provenance_confidence",
        "environment_class",
        "environment_source",
    }
)
KNOWN_DELTA_RECORD_FIELDS: frozenset[str] = frozenset(
    {
        "delta_type",
        "delta_severity",
        "expected_ref",
        "actual_ref",
        "delta_summary",
        "delta_confidence",
    }
)
KNOWN_CLASSIFIABILITY_INPUTS_FIELDS: frozenset[str] = frozenset(
    {
        "extraction_quality_band",
        "coverage_ratio",
        "event_count",
        "has_expected_actual_delta",
        "ambiguity_count",
    }
)

# Dot-paths whose value is itself a dict block to be stripped field-by-field
# (not treated as a single leaf). Recursing here closes the gap where a nested
# field would otherwise ride its parent object's class unclassified.
_NESTED_BLOCK_PATHS: frozenset[str] = frozenset(
    {
        "qualification.classifiability_inputs",
    }
)

# Unregistered nested fields are withheld rather than exposed: a nested field with
# no class is treated as above every tier, so it never leaks while waiting to be
# classified. The build-side completeness test surfaces it as a hard failure.
_WITHHELD_RANK = max(_TIER_RANK.values()) + 1


def visibility_class_for(block: str, field: str) -> str | None:
    """Return the tier class for ``block.field``, or None if unregistered."""

    return VISIBILITY_REGISTRY.get(f"{block}.{field}")


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, _TIER_RANK[_DEFAULT_TIER])


def _strip_block(block: dict[str, Any], *, prefix: str, tier_rank: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in block.items():
        path = f"{prefix}.{key}"
        required = VISIBILITY_REGISTRY.get(path, _DEFAULT_TIER)
        if tier_rank < _tier_rank(required):
            continue
        if path in _NESTED_BLOCK_PATHS and isinstance(value, dict):
            out[key] = _strip_nested_block(value, prefix=path, tier_rank=tier_rank)
        else:
            out[key] = value
    return out


def _strip_nested_block(block: dict[str, Any], *, prefix: str, tier_rank: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in block.items():
        registered = VISIBILITY_REGISTRY.get(f"{prefix}.{key}")
        # An unregistered nested field is withheld at every tier so it can never
        # leak before being classified.
        required_rank = _tier_rank(registered) if registered is not None else _WITHHELD_RANK
        if tier_rank >= required_rank:
            out[key] = value
    return out


def apply_visibility(canonical: dict[str, Any], *, tier: str) -> dict[str, Any]:
    """Return a copy of ``canonical`` with fields above ``tier`` removed.

    The input is never mutated. Blocks not governed by the registry pass through
    untouched.
    """

    rank = _tier_rank(tier)
    result = dict(canonical)

    qualification = canonical.get("qualification")
    if isinstance(qualification, dict):
        result["qualification"] = _strip_block(
            qualification, prefix="qualification", tier_rank=rank
        )

    provenance_environment = canonical.get("provenance_environment")
    if isinstance(provenance_environment, dict):
        result["provenance_environment"] = _strip_block(
            provenance_environment, prefix="provenance_environment", tier_rank=rank
        )

    delta_records = canonical.get("delta_records")
    if isinstance(delta_records, list):
        list_required = VISIBILITY_REGISTRY.get("delta_records", _DEFAULT_TIER)
        if rank < _tier_rank(list_required):
            result["delta_records"] = []
        else:
            result["delta_records"] = [
                _strip_block(record, prefix="delta_records.[]", tier_rank=rank)
                if isinstance(record, dict)
                else record
                for record in delta_records
            ]

    return result
