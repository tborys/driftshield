"""Tests for the v2 recursive redactor (driftshield#109).

Two test families:

* per-rule unit tests covering each redaction category
* corpus canary tests asserting zero ``DRIFTSHIELD_REDACTION_CANARY`` survival
  across the six known transcript shapes
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from driftshield.intake_contract import REQUIRED_REDACTION_FIELDS
from driftshield.recursive_redactor import (
    REDACTION_RULESET_VERSION,
    REDACTOR_VERSION,
    redact,
)
from driftshield.remote_submission import (
    UnknownTranscriptShapeError,
    build_oss_submission_request,
    detect_shape,
    redact_payload,
    redact_payload_with_manifest,
)


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "redactor_corpus"
_CORPUS_NAMES = (
    "claude_code",
    "claude_desktop",
    "codex",
    "openai_chat",
    "langchain",
    "crewai",
)
_CANARY_RE = re.compile(r"DRIFTSHIELD_REDACTION_CANARY_[A-Z0-9_]+")


def _load(name: str) -> dict[str, object]:
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_module_pins_redactor_and_ruleset_versions():
    assert REDACTOR_VERSION.startswith("recursive-redactor.v2")
    assert REDACTION_RULESET_VERSION == "ruleset.v1"


def test_aws_access_key_redacted_anywhere():
    payload = {"events": [{"note": "key=AKIAEXAMPLE12345CANARY"}]}
    result = redact(payload)
    assert "AKIAEXAMPLE12345CANARY" not in json.dumps(result.payload)
    assert any(entry.category == "aws_access_key" for entry in result.entries)


def test_github_pat_redacted_anywhere():
    pat = "ghp_" + "A" * 36
    payload = {"events": [{"note": f"token {pat}"}]}
    result = redact(payload)
    assert pat not in json.dumps(result.payload)
    assert any(entry.category == "github_pat" for entry in result.entries)


def test_openai_key_redacted_anywhere():
    key = "sk-" + "A" * 24
    payload = {"events": [{"note": f"key {key}"}]}
    result = redact(payload)
    assert key not in json.dumps(result.payload)
    assert any(entry.category == "openai_key" for entry in result.entries)


def test_jwt_redacted_anywhere():
    jwt = "eyJhbGciOiJIUzI1NiJ9.payload.signature"
    payload = {"events": [{"note": f"jwt {jwt}"}]}
    result = redact(payload)
    assert jwt not in json.dumps(result.payload)
    assert any(entry.category == "jwt" for entry in result.entries)


def test_ssn_redacted_anywhere():
    payload = {"events": [{"note": "ssn 123-45-6789"}]}
    result = redact(payload)
    assert "123-45-6789" not in json.dumps(result.payload)
    assert any(entry.category == "ssn" for entry in result.entries)


def test_credit_card_only_luhn_valid_is_redacted():
    valid = "4111111111111111"
    invalid = "4111111111111112"
    payload = {"events": [{"note": f"v={valid} iv={invalid}"}]}
    result = redact(payload)
    serialised = json.dumps(result.payload)
    assert valid not in serialised
    assert invalid in serialised
    assert any(entry.category == "credit_card" for entry in result.entries)


def test_home_paths_unix_and_windows_redacted():
    payload = {
        "events": [
            {"note": "open /home/example-user/file.txt"},
            {"note": "open /Users/example-user/file.txt"},
            {"note": "open C:\\Users\\example-user\\file.txt"},
        ]
    }
    result = redact(payload)
    serialised = json.dumps(result.payload)
    assert "/home/example-user" not in serialised
    assert "/Users/example-user" not in serialised
    assert "C:\\\\Users\\\\example-user" not in serialised
    categories = {entry.category for entry in result.entries}
    assert "home_path" in categories


def test_email_redacted_in_free_text():
    payload = {"events": [{"note": "ping alice@example.test"}]}
    result = redact(payload)
    assert "alice@example.test" not in json.dumps(result.payload)
    assert any(entry.category == "email" for entry in result.entries)


def test_tool_io_keys_replaced_with_placeholder_not_dropped():
    payload = {
        "events": [
            {
                "type": "assistant",
                "tool_use": [
                    {
                        "name": "read_file",
                        "arguments": {"path": "/home/example-user/x", "marker": "INNER"},
                    }
                ],
            }
        ]
    }
    result = redact(payload)
    assert "INNER" not in json.dumps(result.payload)
    assert "/home/example-user/x" not in json.dumps(result.payload)
    event = result.payload["events"][0]
    tool = event["tool_use"][0]
    assert tool["name"] == "read_file"
    assert isinstance(tool["arguments"], str)
    assert tool["arguments"].startswith("<REDACTED:tool_io:")


def test_required_redaction_fields_still_dropped_at_top():
    payload = {
        "prompts": ["x"],
        "responses": ["y"],
        "user_identifiers": ["z"],
        "session_id": "s",
    }
    redacted, fields = redact_payload(payload)
    assert "prompts" not in redacted
    assert "responses" not in redacted
    assert "user_identifiers" not in redacted
    assert redacted["session_id"] == "s"
    assert set(fields) == REQUIRED_REDACTION_FIELDS


def test_nested_content_and_text_still_dropped():
    payload = {
        "events": [
            {"type": "user", "content": "SECRET_CONTENT"},
            {"type": "assistant", "text": "SECRET_TEXT"},
        ]
    }
    redacted, _ = redact_payload(payload)
    serialised = json.dumps(redacted)
    assert "SECRET_CONTENT" not in serialised
    assert "SECRET_TEXT" not in serialised


def test_redact_payload_with_manifest_exposes_entries():
    payload = {"events": [{"note": "ssn 123-45-6789"}]}
    result = redact_payload_with_manifest(payload)
    assert any(entry.category == "ssn" for entry in result.entries)
    assert any(entry.path.startswith("events[0].note") for entry in result.entries)


@pytest.mark.parametrize("name", _CORPUS_NAMES)
def test_corpus_fixture_has_no_canary_survival(name: str):
    payload = _load(name)
    redacted, _ = redact_payload(payload)
    serialised = json.dumps(redacted)
    leaks = _CANARY_RE.findall(serialised)
    assert leaks == [], (
        f"canary markers survived redaction in {name} fixture: {leaks}"
    )


@pytest.mark.parametrize("name", _CORPUS_NAMES)
def test_corpus_fixture_detects_known_shape(name: str):
    payload = _load(name)
    shape = detect_shape(payload)
    assert shape is not None, f"shape detection failed for {name}"


def test_detect_shape_returns_none_for_unknown_shape():
    payload = {"some_random_top_level_key": True}
    assert detect_shape(payload) is None


def test_build_request_refuses_unknown_shape_by_default():
    payload = {"some_random_top_level_key": True}
    with pytest.raises(UnknownTranscriptShapeError):
        build_oss_submission_request(source_session_id="s", payload=payload)


def test_build_request_accepts_unknown_shape_when_forced():
    payload = {"some_random_top_level_key": True}
    submission = build_oss_submission_request(
        source_session_id="s",
        payload=payload,
        force_unknown_shape=True,
    )
    assert submission.envelope.source_session_id == "s"
