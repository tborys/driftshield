"""Canonical normalized event pipeline for parser output."""

from __future__ import annotations

import re
from typing import Any

from driftshield.core.models import CanonicalEvent, EventType


NORMALIZED_EVENT_VERSION = "phase-2b-v1"

_SOURCE_REF_KEYS = (
    "tool_use_id",
    "tool_call_id",
    "run_id",
    "parent_run_id",
    "trace_id",
    "task_id",
    "root_run_id",
    "source_message_index",
    "hook_event",
    "hook_name",
)
_ARTIFACT_KEYS = {
    "file_path",
    "path",
    "source_path",
    "output_path",
    "target_path",
    "cwd",
}
_CONSTRAINT_KEYS = {
    "expected_output",
    "constraint",
    "constraints",
    "policy",
    "policies",
    "requirement",
    "requirements",
}
_CONSTRAINT_PATTERN = re.compile(
    r"\b(must|should|do not|don't|without|only|exactly|required|before)\b",
    re.IGNORECASE,
)
_FAILURE_PATTERN = re.compile(
    r"\b(error|failed|failure|exception|timed out|timeout|permission denied|not found)\b",
    re.IGNORECASE,
)
_TOOL_EVENT_TYPES = {EventType.TOOL_CALL, EventType.HANDOFF}


def normalize_events(
    events: list[CanonicalEvent],
    *,
    source_type: str | None = None,
    source_path: str | None = None,
) -> list[CanonicalEvent]:
    """Populate the Phase 2b normalized-event fields on parser output."""

    for ordinal, event in enumerate(events):
        metadata = dict(event.metadata or {})
        if source_type and not metadata.get("source_type"):
            metadata["source_type"] = source_type
        if source_path and not metadata.get("source_path"):
            metadata["source_path"] = source_path
        metadata["normalized_event_version"] = NORMALIZED_EVENT_VERSION
        event.metadata = metadata

        event.ordinal = ordinal
        event.actor = _actor(event)
        event.parent_event_refs = _parent_refs(event)
        event.source_refs = _source_refs(event, source_type=source_type, source_path=source_path)
        event.artifact_refs = _artifact_refs(event)
        event.constraints = _constraints(event)
        event.failure_context = _failure_context(event)
        event.tool_activity = _tool_activity(event)
        event.summary = _summary(event)
        event.ambiguities = _ambiguities(event)

    return events


def _actor(event: CanonicalEvent) -> dict[str, str]:
    actor = dict(event.actor or {})
    actor.setdefault("id", event.agent_id or "unknown")
    actor.setdefault("role", _actor_role(event))
    return actor


def _actor_role(event: CanonicalEvent) -> str:
    if event.agent_id == "user":
        return "user"
    if event.agent_id == "system":
        return "system"
    if event.event_type in _TOOL_EVENT_TYPES:
        return "assistant"
    return (event.actor or {}).get("role") or "assistant"


def _parent_refs(event: CanonicalEvent) -> list[Any]:
    refs = list(event.parent_event_refs or [])
    if event.parent_event_id is not None and event.parent_event_id not in refs:
        refs.insert(0, event.parent_event_id)
    return refs


def _source_refs(
    event: CanonicalEvent,
    *,
    source_type: str | None,
    source_path: str | None,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []

    parser_name = (
        source_type
        or str(event.metadata.get("source_type", "")).strip()
        or None
    )
    if parser_name:
        refs.append({"kind": "parser", "value": parser_name})

    path_value = source_path or event.metadata.get("source_path")
    if path_value:
        refs.append({"kind": "source_path", "value": str(path_value)})

    for key in _SOURCE_REF_KEYS:
        value = event.metadata.get(key)
        if value is None or value == "":
            continue
        refs.append({"kind": key, "value": str(value)})

    return _dedupe_refs(refs)


def _artifact_refs(event: CanonicalEvent) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for payload_name, payload in (
        ("inputs", event.inputs),
        ("outputs", event.outputs),
        ("metadata", event.metadata),
    ):
        refs.extend(_extract_keyed_refs(payload, payload_name, _ARTIFACT_KEYS))
    return _dedupe_refs(refs)


def _constraints(event: CanonicalEvent) -> list[dict[str, str]]:
    constraints: list[dict[str, str]] = []

    for payload_name, payload in (
        ("inputs", event.inputs),
        ("outputs", event.outputs),
        ("metadata", event.metadata),
    ):
        constraints.extend(_extract_keyed_refs(payload, payload_name, _CONSTRAINT_KEYS, key_name="kind"))

    for text in _text_fragments(event):
        if not _CONSTRAINT_PATTERN.search(text):
            continue
        constraints.append(
            {
                "kind": "message_constraint",
                "value": text,
                "source": "outputs.text",
            }
        )

    return _dedupe_refs(constraints)


def _failure_context(event: CanonicalEvent) -> dict[str, Any] | None:
    signals: list[str] = []
    error = _first_non_empty(
        event.outputs.get("error"),
        event.metadata.get("error"),
    )
    is_error = bool(event.outputs.get("is_error"))

    if error:
        signals.append("explicit_error")
    if is_error:
        signals.append("tool_marked_error")

    failure_language = any(_FAILURE_PATTERN.search(text) for text in _text_fragments(event))
    if failure_language:
        signals.append("failure_language")

    if not signals:
        return None

    status = "error" if error or is_error else "warning"
    return {
        "status": status,
        "error": str(error) if error else None,
        "signals": sorted(set(signals)),
        "declared_failure": bool(error or is_error or failure_language),
    }


def _tool_activity(event: CanonicalEvent) -> dict[str, Any] | None:
    if event.event_type not in _TOOL_EVENT_TYPES:
        return None

    failure = event.failure_context or {}
    if failure.get("status") == "error":
        status = "error"
    elif event.outputs:
        status = "completed"
    else:
        status = "pending"

    return {
        "name": event.action,
        "category": event.metadata.get("semantic_action_category"),
        "raw_name": event.metadata.get("raw_action") or event.action,
        "status": status,
        "input_keys": sorted(str(key) for key in event.inputs.keys()),
        "has_outputs": bool(event.outputs),
    }


def _summary(event: CanonicalEvent) -> str:
    if event.summary:
        return event.summary

    if event.event_type in _TOOL_EVENT_TYPES:
        artifact = next((ref["value"] for ref in event.artifact_refs), None)
        suffix = f" on {artifact}" if artifact else ""
        if event.failure_context and event.failure_context.get("status") == "error":
            return f"{event.action} reported an error{suffix}"
        if event.outputs:
            return f"{event.action} completed{suffix}"
        return f"{event.action} invoked{suffix}"

    for text in _text_fragments(event):
        cleaned = " ".join(text.split())
        if cleaned:
            return cleaned[:160]

    return event.action or event.event_type.value.lower()


def _ambiguities(event: CanonicalEvent) -> list[str]:
    ambiguities: list[str] = []

    if not event.source_refs:
        ambiguities.append("missing_source_ref")
    if event.ordinal not in (None, 0) and not event.parent_event_refs:
        ambiguities.append("missing_parent_ref")
    if event.actor is None or event.actor.get("id") in {None, "", "unknown"}:
        ambiguities.append("missing_actor")
    if event.event_type in _TOOL_EVENT_TYPES and not event.inputs:
        ambiguities.append("missing_tool_inputs")
    if event.event_type in _TOOL_EVENT_TYPES and not event.outputs:
        ambiguities.append("missing_tool_outputs")
    if event.failure_context and event.failure_context.get("status") == "warning":
        ambiguities.append("failure_inferred_from_text")

    return sorted(set(ambiguities))


def _extract_keyed_refs(
    payload: object,
    payload_name: str,
    keys: set[str],
    *,
    key_name: str = "kind",
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, (str, int, float)):
                refs.append({key_name: key, "value": str(value), "source": payload_name})
            elif isinstance(value, dict):
                refs.extend(_extract_keyed_refs(value, f"{payload_name}.{key}", keys, key_name=key_name))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    refs.extend(
                        _extract_keyed_refs(
                            item,
                            f"{payload_name}.{key}[{index}]",
                            keys,
                            key_name=key_name,
                        )
                    )
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            refs.extend(_extract_keyed_refs(item, f"{payload_name}[{index}]", keys, key_name=key_name))
    return refs


def _text_fragments(event: CanonicalEvent) -> list[str]:
    texts: list[str] = []

    output_text = event.outputs.get("text")
    if isinstance(output_text, str) and output_text.strip():
        texts.append(output_text.strip())

    result = event.outputs.get("result")
    if isinstance(result, str) and result.strip():
        texts.append(result.strip())

    error = event.outputs.get("error")
    if isinstance(error, str) and error.strip():
        texts.append(error.strip())

    return texts


def _dedupe_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    deduped: list[dict[str, str]] = []
    for ref in refs:
        key = tuple(sorted((str(name), str(value)) for name, value in ref.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
