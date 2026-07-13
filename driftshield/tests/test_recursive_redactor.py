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
    assert REDACTOR_VERSION.startswith("recursive-redactor.v3")
    assert REDACTION_RULESET_VERSION == "ruleset.v3"


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


def test_content_block_tool_use_input_replaced_with_placeholder_object():
    """driftshield#158: native ``message.content`` list of typed blocks.
    ``tool_use`` keeps ``type``/``id``/``name`` and gets ``input`` replaced
    by a placeholder OBJECT (not string), so a downstream re-parse never
    hits a non-mapping ``event.inputs``.
    """
    payload = {
        "events": [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Read",
                            "input": {"file_path": "/home/example-user/secrets.txt"},
                        }
                    ]
                },
            }
        ]
    }
    result = redact(payload)
    serialised = json.dumps(result.payload)
    assert "/home/example-user/secrets.txt" not in serialised

    block = result.payload["events"][0]["message"]["content"][0]
    assert block == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "Read",
        "input": block["input"],
    }
    assert isinstance(block["input"], dict)
    assert block["input"]["redacted"].startswith("<REDACTED:tool_io:")


def test_content_block_text_replaced_type_retained():
    payload = {
        "events": [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "SECRET_NARRATIVE"}]},
            }
        ]
    }
    result = redact(payload)
    block = result.payload["events"][0]["message"]["content"][0]
    assert block["type"] == "text"
    assert "SECRET_NARRATIVE" not in json.dumps(result.payload)
    assert block["text"].startswith("<REDACTED:prompt_response:")


def test_content_block_tool_result_body_replaced_metadata_retained():
    payload = {
        "events": [
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "is_error": True,
                            "content": "SECRET_TOOL_OUTPUT",
                        }
                    ]
                },
            }
        ]
    }
    result = redact(payload)
    block = result.payload["events"][0]["message"]["content"][0]
    assert block["tool_use_id"] == "toolu_1"
    assert block["is_error"] is True
    assert "SECRET_TOOL_OUTPUT" not in json.dumps(result.payload)
    assert block["content"].startswith("<REDACTED:prompt_response:")


def test_content_block_thinking_dropped_entirely():
    payload = {
        "events": [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "SECRET_CHAIN_OF_THOUGHT"},
                        {"type": "text", "text": "visible reply"},
                    ]
                },
            }
        ]
    }
    result = redact(payload)
    blocks = result.payload["events"][0]["message"]["content"]
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert "SECRET_CHAIN_OF_THOUGHT" not in json.dumps(result.payload)


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


def test_nested_content_and_text_redacted_in_place_not_dropped():
    """ruleset.v3 (driftshield#158): a plain-string ``content``/``text`` value
    is replaced with a placeholder in place, not deleted, so a downstream
    re-parse still finds the key.
    """
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
    assert redacted["events"][0]["content"].startswith("<REDACTED:prompt_response:")
    assert redacted["events"][1]["text"].startswith("<REDACTED:prompt_response:")


def test_redact_payload_with_manifest_exposes_entries():
    payload = {"events": [{"note": "ssn 123-45-6789"}]}
    result = redact_payload_with_manifest(payload)
    assert any(entry.category == "ssn" for entry in result.entries)
    assert any(entry.path.startswith("events[0].note") for entry in result.entries)


def test_claude_code_error_body_dropped_api_error_status_retained():
    """Confirmed live leak: a native Claude Code API-failure record nests a
    free-text ``error`` body (bearer token + 401 headers) plus a bare
    ``api_error_status`` HTTP code. The free-text body must be dropped; the
    bare status code is a non-sensitive failure-mechanism code and is retained.
    """
    payload = {
        "events": [
            {
                "event": {
                    "error": "401 Unauthorized: Bearer sk-leakedtokenvalue\r\n"
                    "www-authenticate: ... host internal.example",
                    "api_error_status": 401,
                }
            }
        ]
    }
    result = redact(payload)
    serialised = json.dumps(result.payload)

    assert "sk-leakedtokenvalue" not in serialised
    assert "www-authenticate" not in serialised
    assert any(
        entry.category == "dropped_key" and entry.path.endswith(".error")
        for entry in result.entries
    )
    event = result.payload["events"][0]["event"]
    assert "error" not in event
    # api_error_status is a bare HTTP status code, not free text -> retained.
    assert event["api_error_status"] == 401


def test_verbatim_failure_body_keys_dropped_at_any_depth():
    """``stdout`` / ``stderr`` / ``toolUseResult`` / ``details`` / ``raw`` ride
    verbatim into ``events[]`` via the native-JSONL passthrough and can carry
    command output, tracebacks and tool-argument text. None are read by the
    matcher by name, so all are dropped wherever they nest.
    """
    payload = {
        "events": [
            {
                "toolUseResult": {
                    "stdout": "leak STDOUT_CANARY /home/example-user/secrets.txt",
                    "stderr": "leak STDERR_CANARY Traceback host internal.example",
                    "interrupted": False,
                },
            },
            {"toolUseResult": "Error: STRINGFORM_CANARY leaked body"},
            {"outputs": {"details": {"diag": "DETAILS_CANARY leaked"}}},
            {"inputs": {"raw": "RAW_CANARY unparseable tool arguments"}},
        ]
    }
    result = redact(payload)
    serialised = json.dumps(result.payload)

    for canary in (
        "STDOUT_CANARY",
        "STDERR_CANARY",
        "STRINGFORM_CANARY",
        "DETAILS_CANARY",
        "RAW_CANARY",
    ):
        assert canary not in serialised, f"{canary} survived redaction"

    dropped_paths = {
        entry.path for entry in result.entries if entry.category == "dropped_key"
    }
    assert any(p.endswith("toolUseResult") for p in dropped_paths)
    assert any(p.endswith("details") for p in dropped_paths)
    assert any(p.endswith("raw") for p in dropped_paths)


def test_claude_code_corpus_api_error_status_retained():
    """The claude_code corpus fixture carries a native API-failure record.
    Its free-text ``error`` body is dropped by the canary-survival test; the
    bare ``api_error_status`` HTTP code is retained.
    """
    redacted, _ = redact_payload(_load("claude_code"))
    statuses = [
        event["event"]["api_error_status"]
        for event in redacted.get("events", [])
        if isinstance(event, dict) and isinstance(event.get("event"), dict)
        and "api_error_status" in event["event"]
    ]
    assert 401 in statuses


def test_matcher_signal_keys_retained_not_blanket_dropped():
    """Guard against over-broad drops. ``error_code`` / ``status`` / ``is_error``
    are matcher mechanism signals (bare codes/enums/flags), not free-text
    bodies, and must survive redaction.
    """
    payload = {
        "events": [
            {
                "structured_payload": {
                    "result_status": "error",
                    "error_code": "tool_error",
                },
                "tool_activity": {"status": "error"},
                "is_error": True,
            }
        ]
    }
    result = redact(payload)
    event = result.payload["events"][0]

    assert event["structured_payload"]["result_status"] == "error"
    assert event["structured_payload"]["error_code"] == "tool_error"
    assert event["tool_activity"]["status"] == "error"
    assert event["is_error"] is True


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


# ---------------------------------------------------------------------------
# signature_summary stays byte-identical at envelope level
# ---------------------------------------------------------------------------


def test_signature_summary_at_envelope_level_is_untouched():
    """The redactor only walks ``payload``. A sibling ``signature_summary``
    block must come out the other side byte-for-byte identical.
    """
    import copy
    from driftshield.intake_contract import (
        REDACTION_MANIFEST_VERSION,
        REQUIRED_REDACTION_FIELDS,
        SIGNATURE_SUMMARY_VERSION,
        SUPPORTED_CONTRACT_VERSION,
        RedactionManifest,
        SignatureSummary,
        SignatureSummaryEntry,
        SubmissionEnvelope,
    )

    summary = SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=[
            SignatureSummaryEntry(
                signature_id="sig-abc",
                match_status="matched",
                community_pack_id="community-general",
                community_pack_version="1.0.0",
                matcher_id="phase-3g-deterministic-v1",
                matcher_version="phase-3g-deterministic-rules-v1",
                confidence=0.9,
                confidence_band="high",
            )
        ],
    )

    envelope = SubmissionEnvelope(
        source_system="oss",
        source_session_id="sess-1",
        schema_version=SUPPORTED_CONTRACT_VERSION,
        payload={
            "session_id": "sess-1",
            "events": [{"type": "user", "content": "LEAK_CANARY_PROMPT"}],
        },
        payload_size_bytes=64,
        redaction_manifest=RedactionManifest(
            manifest_version=REDACTION_MANIFEST_VERSION,
            redaction_applied=True,
            redacted_fields=sorted(REQUIRED_REDACTION_FIELDS),
        ),
        signature_summary=summary,
    )

    before = copy.deepcopy(envelope.signature_summary)
    before_json = envelope.signature_summary.model_dump_json()

    # Run the redactor against ONLY the payload, mirroring the build-time call site.
    result = redact(envelope.payload)
    assert "LEAK_CANARY_PROMPT" not in json.dumps(result.payload)

    after_json = envelope.signature_summary.model_dump_json()
    assert envelope.signature_summary == before
    assert after_json == before_json
