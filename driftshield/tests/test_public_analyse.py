"""Tests for the public ``analyse`` entrypoint (driftshield#148).

``analyse`` is the stable, content based, DB free chain an external host (the
DriftShield intel cloud worker) calls to get the same verdict the local
dashboard produces. These tests pin the contract: content detection, verdict
parity (qualified_failure / unclassified / not_classifiable), the OSS safe
signature summary shape, and graceful handling of empty or unparseable input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftshield.public import ANALYSE_SCHEMA_VERSION, analyse, detect_source

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
_REAL_TRAJECTORY = FIXTURES / "sample_openclaw_trajectory.json"
_CLAUDE_CODE = FIXTURES / "sample_claude_code_session.jsonl"
_CONSTRAINT_VIOLATION = FIXTURES / "dogfood" / "constraint_violation_session.jsonl"
_POLICY_DIVERGENCE = FIXTURES / "dogfood" / "policy_divergence_session.jsonl"
_CLEAN = FIXTURES / "dogfood" / "clean_session.jsonl"

# One fixture per supported parser, mapping the file to the source name
# ``auto`` detection must return. Pins the "any supported source + auto-detect"
# contract so a new parser added to cli.parsers without a sniffer is caught.
_SOURCE_FIXTURES = {
    "openclaw_trajectory": _REAL_TRAJECTORY,
    "claude_code": _CLAUDE_CODE,
    "codex_cli": FIXTURES / "sample_codex_cli_session.jsonl",
    "codex_desktop": FIXTURES / "sample_codex_desktop_session.json",
    "claude_desktop": FIXTURES / "sample_claude_desktop_session.json",
    "crewai": FIXTURES / "sample_crewai_session.json",
    "langchain": FIXTURES / "sample_langchain_session.json",
}


# --------------------------------------------------------------------------- #
# Content based source detection (the cloud has no file path to key on)
# --------------------------------------------------------------------------- #


def test_detect_real_openclaw_trajectory_wrapper() -> None:
    body = _REAL_TRAJECTORY.read_text()
    assert detect_source(body) == "openclaw_trajectory"


def test_detect_claude_code_with_leading_non_identifying_record() -> None:
    # The sample opens with a file-history-snapshot record before any
    # user/assistant line; detection must scan past it.
    body = _CLAUDE_CODE.read_text()
    assert detect_source(body) == "claude_code"


def test_detect_openclaw_trajectory_jsonl_lines() -> None:
    line = json.dumps(
        {"runId": "r", "traceId": "t", "schemaVersion": 1, "seq": 1, "source": "runtime", "type": "session.started"}
    )
    assert detect_source(line) == "openclaw_trajectory"


def test_detect_returns_none_for_unrecognised_content() -> None:
    assert detect_source('{"hello": "world"}') is None
    assert detect_source("not json at all") is None
    assert detect_source("") is None


@pytest.mark.parametrize("expected,fixture", list(_SOURCE_FIXTURES.items()))
def test_auto_detect_covers_every_supported_parser(expected: str, fixture: Path) -> None:
    # The "any supported source + auto-detect" contract: every parser in
    # cli.parsers must be reachable via source="auto", not just the three
    # original detections. A supported source that falls through to raw is a
    # silent failure (the bug this whole change set fixes).
    body = fixture.read_text()
    assert detect_source(body) == expected
    out = analyse(body)  # auto
    assert out["source_format"] == expected
    assert out["event_count"] > 0  # parsed, not degraded to raw/not_classifiable


def test_auto_detect_set_matches_parser_registry() -> None:
    # Guard against adding a parser without a sniffer + fixture here.
    from driftshield.cli.parsers import PARSERS

    # ``openclaw`` shares the session-transcript path; it is exercised via the
    # detection unit test rather than a separate fixture.
    covered = set(_SOURCE_FIXTURES) | {"openclaw"}
    missing = set(PARSERS) - covered
    assert not missing, f"parsers without auto-detect coverage: {sorted(missing)}"


# --------------------------------------------------------------------------- #
# Verdict parity with the local dashboard
# --------------------------------------------------------------------------- #


def test_real_aborted_run_is_unclassified_not_a_fake_match() -> None:
    # The real captured OSS payload is a user-aborted, tool-less run. Honest
    # verdict parity: unclassified, zero matches. NOT a fabricated abort match.
    out = analyse(_REAL_TRAJECTORY.read_text())
    assert out["source_format"] == "openclaw_trajectory"
    assert out["schema_version"] == ANALYSE_SCHEMA_VERSION
    assert out["qualification"]["qualification_state"] == "unclassified"
    assert out["signature_summary"]["matches"] == []
    assert out["event_count"] > 0
    assert out["canonical_analysis"] is not None


def test_real_failure_run_qualifies_and_matches() -> None:
    # A genuine failure transcript produces qualified_failure + >=1 match,
    # proving the matcher fires through the same chain (not just parsing).
    out = analyse(_CONSTRAINT_VIOLATION.read_text())
    assert out["qualification"]["qualification_state"] == "qualified_failure"
    matches = out["signature_summary"]["matches"]
    assert len(matches) >= 1
    entry = matches[0]
    # OSS safe shape: identification + provenance + status/confidence/band only.
    assert entry["signature_id"]
    assert entry["match_status"] == "matched"
    assert entry["confidence_band"] in {"high", "medium", "low", "very_low"}
    assert entry["community_pack_id"]
    assert entry["matcher_id"]


def test_policy_divergence_run_qualifies_and_matches() -> None:
    out = analyse(_POLICY_DIVERGENCE.read_text())
    assert out["qualification"]["qualification_state"] == "qualified_failure"
    assert len(out["signature_summary"]["matches"]) >= 1


def test_clean_run_has_no_matches() -> None:
    out = analyse(_CLEAN.read_text())
    assert out["signature_summary"]["matches"] == []


# --------------------------------------------------------------------------- #
# Trajectory tool-failure extraction parity (intel#228)
#
# A genuine structural tool failure in an OpenClaw trajectory must reach the same
# verdict a claude_code transcript with the equivalent failure reaches. The real
# captured prod payload is a user abort, which stays honestly unclassified.
# --------------------------------------------------------------------------- #


def _trajectory(events: list[dict]) -> str:
    return json.dumps(
        {
            "events": events,
            "metadata": {"environment": "test"},
            "session_id": "00000000-0000-0000-0000-0000000000aa",
        }
    )


def _traj_record(seq: int, record_type: str, data: dict) -> dict:
    return {
        "ts": f"2026-05-03T05:25:{seq:02d}.000Z",
        "seq": seq,
        "type": record_type,
        "data": data,
        "runId": "00000000-0000-0000-0000-0000000000bb",
        "source": "runtime",
        "modelId": "gpt-5.4",
        "traceId": "00000000-0000-0000-0000-0000000000aa",
        "schemaVersion": 1,
        "sessionId": "00000000-0000-0000-0000-0000000000aa",
        "sessionKey": "k",
        "sourceSeq": seq,
        "modelApi": "openai-codex-responses",
    }


def _claude_code_lines(lines: list[dict]) -> str:
    return "\n".join(json.dumps(line) for line in lines)


# The same logical failure expressed in both formats: a tool the runtime ran
# returned an error, then the run claimed completion without recovering.
_TRAJECTORY_TOOL_FAILURE = _trajectory(
    [
        _traj_record(4, "prompt.submitted", {"prompt": "Run the build and finish."}),
        _traj_record(5, "model.completed", {"assistantTexts": ["Running the build."]}),
        _traj_record(
            6,
            "trace.artifacts",
            {
                "finalStatus": "success",
                "toolMetas": [{"toolName": "exec", "meta": "make build", "isError": True}],
            },
        ),
        _traj_record(7, "model.completed", {"assistantTexts": ["All done, build complete."]}),
        _traj_record(8, "session.ended", {"status": "success"}),
    ]
)

_CLAUDE_CODE_TOOL_FAILURE = _claude_code_lines(
    [
        {
            "sessionId": "s1",
            "type": "user",
            "timestamp": "2026-03-01T11:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Run the build and finish."}]},
        },
        {
            "sessionId": "s1",
            "type": "assistant",
            "timestamp": "2026-03-01T11:00:01Z",
            "message": {"model": "c", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "make build"}}]},
        },
        {
            "sessionId": "s1",
            "type": "user",
            "timestamp": "2026-03-01T11:00:02Z",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "error: build failed"}]},
        },
        {
            "sessionId": "s1",
            "type": "assistant",
            "timestamp": "2026-03-01T11:00:03Z",
            "message": {"model": "c", "content": [{"type": "text", "text": "All done, build complete."}]},
        },
    ]
)


def test_trajectory_tool_failure_qualifies_and_matches() -> None:
    out = analyse(_TRAJECTORY_TOOL_FAILURE)
    assert out["source_format"] == "openclaw_trajectory"
    assert out["qualification"]["qualification_state"] == "qualified_failure"
    matches = out["signature_summary"]["matches"]
    assert len(matches) >= 1
    mechanisms = {m["signature_id"] for m in matches}
    assert "mechanism:tool_misuse" in mechanisms


def test_trajectory_and_claude_code_tool_failure_reach_same_state() -> None:
    # Verdict parity across parsers: the same logical failure must produce the
    # same qualification_state, whichever format carried it.
    traj_out = analyse(_TRAJECTORY_TOOL_FAILURE)
    cc_out = analyse(_CLAUDE_CODE_TOOL_FAILURE, source="claude_code")
    assert (
        traj_out["qualification"]["qualification_state"]
        == cc_out["qualification"]["qualification_state"]
        == "qualified_failure"
    )
    assert {m["signature_id"] for m in cc_out["signature_summary"]["matches"]} >= {"mechanism:tool_misuse"}
    assert {m["signature_id"] for m in traj_out["signature_summary"]["matches"]} >= {"mechanism:tool_misuse"}


def test_trajectory_abort_stays_unclassified_with_no_match() -> None:
    # An aborted run carries is_error on the model/session events but no failed
    # tool. It must stay honestly unclassified, never a fabricated tool match.
    aborted = _trajectory(
        [
            _traj_record(4, "prompt.submitted", {"prompt": "do x"}),
            _traj_record(
                5,
                "model.completed",
                {"aborted": True, "externalAbort": True, "error": "prompt error", "is_error": True},
            ),
            _traj_record(6, "trace.artifacts", {"finalStatus": "error", "toolMetas": []}),
            _traj_record(7, "session.ended", {"status": "error", "error": "run aborted", "aborted": True}),
        ]
    )
    out = analyse(aborted)
    assert out["qualification"]["qualification_state"] == "unclassified"
    assert out["signature_summary"]["matches"] == []


def test_trajectory_thin_telemetry_stays_unclassified() -> None:
    # A thin success trajectory (telemetry, no failed tool) carries no material
    # delta and must not be forced into a match.
    thin = _trajectory(
        [
            _traj_record(4, "prompt.submitted", {"prompt": "summarise the log"}),
            _traj_record(5, "model.completed", {"assistantTexts": ["Summary done."]}),
            _traj_record(
                6,
                "trace.artifacts",
                {"finalStatus": "success", "toolMetas": [{"toolName": "read", "meta": "open log"}]},
            ),
            _traj_record(7, "session.ended", {"status": "success"}),
        ]
    )
    out = analyse(thin)
    assert out["qualification"]["qualification_state"] == "unclassified"
    assert out["signature_summary"]["matches"] == []


@pytest.mark.parametrize(
    "source", ["codex_desktop", "claude_desktop"]
)
def test_desktop_single_object_parses_when_pretty_printed(source: str) -> None:
    # Regression: LocalChatTranscriptParser.parse() previously routed a
    # pretty-printed single JSON object (newline present) to the JSONL path and
    # raised. A content based caller (analyse) must handle both pretty and
    # minified single-object transcripts.
    pretty = _SOURCE_FIXTURES[source].read_text()
    assert "\n" in pretty  # the fixture is pretty-printed
    out_pretty = analyse(pretty, source=source)
    minified = json.dumps(json.loads(pretty), separators=(",", ":"))
    out_min = analyse(minified, source=source)
    assert out_pretty["event_count"] > 0
    assert out_pretty["event_count"] == out_min["event_count"]


# --------------------------------------------------------------------------- #
# Robustness: never raise on bad input (ingest must not 500)
# --------------------------------------------------------------------------- #


def test_empty_content_returns_not_classifiable() -> None:
    out = analyse("")
    assert out["source_format"] == "raw"
    assert out["qualification"]["qualification_state"] == "not_classifiable"
    assert out["signature_summary"]["matches"] == []
    assert out["event_count"] == 0


def test_unrecognised_content_returns_not_classifiable() -> None:
    out = analyse('{"some": "unknown shape"}')
    assert out["qualification"]["qualification_state"] == "not_classifiable"


def test_bytes_input_is_accepted() -> None:
    out = analyse(_REAL_TRAJECTORY.read_bytes())
    assert out["source_format"] == "openclaw_trajectory"


def test_explicit_source_overrides_detection() -> None:
    out = analyse(_REAL_TRAJECTORY.read_text(), source="openclaw_trajectory")
    assert out["source_format"] == "openclaw_trajectory"


def test_unsupported_explicit_source_returns_not_classifiable() -> None:
    out = analyse(_REAL_TRAJECTORY.read_text(), source="does_not_exist")
    assert out["source_format"] == "raw"
    assert out["qualification"]["qualification_state"] == "not_classifiable"


@pytest.mark.parametrize(
    "fixture",
    [_REAL_TRAJECTORY, _CLAUDE_CODE, _CONSTRAINT_VIOLATION, _CLEAN],
)
def test_signature_summary_is_serialisable(fixture: Path) -> None:
    # The whole verdict must round-trip through JSON (it is persisted as jsonb).
    out = analyse(fixture.read_text())
    json.dumps(out)
