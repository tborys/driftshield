"""Unit tests for driftshield.cli._session_payload.load_session_payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield.cli._session_payload import load_session_payload


def test_loads_single_json_object(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    payload = {"events": [{"a": 1}], "session_id": "sess-1"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_session_payload(path)

    assert loaded == payload


def test_loads_jsonl_collects_events_and_session_id(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "assistant", "sessionId": "sess-2", "x": 1}),
        json.dumps({"type": "user", "y": 2}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    loaded = load_session_payload(path)

    assert loaded["session_id"] == "sess-2"
    assert isinstance(loaded["events"], list)
    assert len(loaded["events"]) == 2
    assert loaded["events"][0]["type"] == "assistant"
    assert loaded["events"][1]["type"] == "user"


def test_jsonl_without_session_id_omits_field(tmp_path: Path) -> None:
    """Multi-line JSONL whose lines lack ``sessionId`` produces a payload
    with ``events`` but no ``session_id``. A single-line JSONL parses as
    a JSON object and takes the object branch (see
    ``test_loads_single_json_object``); two lines forces the JSONL branch.
    """
    path = tmp_path / "session.jsonl"
    path.write_text(
        json.dumps({"type": "user", "x": 1})
        + "\n"
        + json.dumps({"type": "assistant", "y": 2})
        + "\n",
        encoding="utf-8",
    )

    loaded = load_session_payload(path)

    assert "session_id" not in loaded
    assert loaded["events"][0]["type"] == "user"
    assert loaded["events"][1]["type"] == "assistant"


def test_jsonl_drops_unparseable_lines(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "sessionId": "sess-3"}),
                "{not parseable",
                json.dumps({"type": "user"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_session_payload(path)

    assert loaded["session_id"] == "sess-3"
    assert len(loaded["events"]) == 2


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        load_session_payload(path)


def test_top_level_array_raises(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text(json.dumps([{"events": []}]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_session_payload(path)


def test_non_json_garbage_raises(tmp_path: Path) -> None:
    path = tmp_path / "garbage.txt"
    path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(ValueError, match="no parseable JSONL records"):
        load_session_payload(path)


def test_malformed_json_object_falls_through_to_jsonl_and_raises(tmp_path: Path) -> None:
    """A file that looks like a malformed JSON object falls through to the
    JSONL branch (single unparseable line → no events → ValueError).
    """
    path = tmp_path / "broken.json"
    path.write_text('{"events": [}', encoding="utf-8")

    with pytest.raises(ValueError, match="no parseable JSONL records"):
        load_session_payload(path)
