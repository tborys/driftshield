"""Behaviour tests for the public door: ``analyse_run`` and ``submit``.

Everything the engine does (format detection, parsing, evaluation, redaction,
transport) is exercised through these two calls, the only public API.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

import driftshield
from driftshield import (
    AnalysedRun,
    NoParseableEventsError,
    SubmitError,
    UnsupportedFormatError,
    analyse_run,
    submit,
)
from driftshield.cli.main import app
from driftshield.recursive_redactor import redact

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
REDACTOR_CORPUS = Path(__file__).parent / "fixtures" / "redactor_corpus"
_TRAJECTORY = FIXTURES / "sample_openclaw_trajectory.json"
_CLAUDE_CODE = FIXTURES / "sample_claude_code_session.jsonl"
_CONSTRAINT_VIOLATION = FIXTURES / "dogfood" / "constraint_violation_session.jsonl"
_CLEAN = FIXTURES / "dogfood" / "clean_session.jsonl"
_INTAKE_URL = "https://intake.example.test/v1/oss/submissions"

# One fixture per supported parser and the format ``analyse_run`` must detect
# from content alone (no path hint is passed).
_SOURCE_FIXTURES = {
    "openclaw_trajectory": _TRAJECTORY,
    "claude_code": _CLAUDE_CODE,
    "codex_cli": FIXTURES / "sample_codex_cli_session.jsonl",
    "codex_desktop": FIXTURES / "sample_codex_desktop_session.json",
    "claude_desktop": FIXTURES / "sample_claude_desktop_session.json",
    "crewai": FIXTURES / "sample_crewai_session.json",
    "langchain": FIXTURES / "sample_langchain_session.json",
}

_OPENCLAW_SESSION_LINES = "\n".join(
    [
        '{"type":"session","id":"session-1","timestamp":"2026-03-21T20:00:00Z"}',
        '{"type":"message","id":"u1","parentId":null,"timestamp":"2026-03-21T20:00:01Z",'
        '"message":{"role":"user","content":[{"type":"text","text":"Please check this repo."}]}}',
        '{"type":"message","id":"a1","parentId":"u1","timestamp":"2026-03-21T20:00:02Z",'
        '"message":{"role":"assistant","content":[{"type":"text","text":"I checked it."}]}}',
    ]
)


def _claude_code_lines(lines: list[dict]) -> str:
    return "\n".join(json.dumps(line) for line in lines)


def _cc(role: str, content: list[dict], ts: str) -> dict:
    message = {"role": role, "content": content} if role == "user" else {"model": "c", "content": content}
    return {"sessionId": "s1", "type": role, "timestamp": ts, "message": message}


_CLAUDE_CODE_TOOL_FAILURE = _claude_code_lines(
    [
        _cc("user", [{"type": "text", "text": "Run the build and finish."}], "2026-03-01T11:00:00Z"),
        _cc(
            "assistant",
            [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "make build"}}],
            "2026-03-01T11:00:01Z",
        ),
        _cc(
            "user",
            [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "error: build failed"}],
            "2026-03-01T11:00:02Z",
        ),
        _cc("assistant", [{"type": "text", "text": "All done, build complete."}], "2026-03-01T11:00:03Z"),
    ]
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
        "provider": "openai",
        "traceId": "00000000-0000-0000-0000-0000000000aa",
        "schemaVersion": 1,
        "sessionId": "00000000-0000-0000-0000-0000000000aa",
    }


def _trajectory(events: list[dict]) -> str:
    return json.dumps({"events": events, "metadata": {"environment": "test"}, "session_id": "t-1"})


_TRAJECTORY_TOOL_FAILURE = _trajectory(
    [
        _traj_record(4, "prompt.submitted", {"prompt": "Run the build and finish."}),
        _traj_record(5, "model.completed", {"assistantTexts": ["Running the build."]}),
        _traj_record(
            6,
            "trace.artifacts",
            {"finalStatus": "success", "toolMetas": [{"toolName": "exec", "meta": "make build", "isError": True}]},
        ),
        _traj_record(7, "model.completed", {"assistantTexts": ["All done, build complete."]}),
        _traj_record(8, "session.ended", {"status": "success"}),
    ]
)


# --------------------------------------------------------------------------- #
# The public surface
# --------------------------------------------------------------------------- #


def test_package_exports_exactly_the_door():
    assert set(driftshield.__all__) == {
        "AnalysedRun",
        "Finding",
        "NoParseableEventsError",
        "SignatureHit",
        "SubmitError",
        "SubmitReceipt",
        "UnsupportedFormatError",
        "analyse_run",
        "submit",
    }
    for internal in ("detect_source", "detect_parser", "detect_shape", "analyse", "get_parser"):
        assert not hasattr(driftshield, internal)


# --------------------------------------------------------------------------- #
# analyse_run: detection, inputs, warnings, errors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("expected,fixture", list(_SOURCE_FIXTURES.items()))
def test_content_alone_detects_every_supported_format(expected: str, fixture: Path):
    run = analyse_run(fixture.read_bytes())
    assert run.detected_format == expected
    assert run.events and run.source is None
    assert run.warnings == []


def test_detection_covers_the_whole_parser_registry():
    from driftshield.parsers.registry import PARSERS

    assert set(PARSERS) == set(_SOURCE_FIXTURES) | {"openclaw"}


def test_openclaw_session_lines_detect_from_content():
    run = analyse_run(_OPENCLAW_SESSION_LINES)
    assert run.detected_format == "openclaw"
    assert len(run.events) == 2


def test_str_and_bytes_give_the_same_run():
    as_bytes = analyse_run(_CLAUDE_CODE.read_bytes(), run_id=uuid.UUID(int=1))
    as_str = analyse_run(_CLAUDE_CODE.read_text(), run_id=uuid.UUID(int=1))
    assert [e.id for e in as_bytes.events] == [e.id for e in as_str.events]
    assert as_bytes.redacted_transcript == as_str.redacted_transcript


def test_content_decides_when_the_path_hint_is_wrong():
    # A codex_cli transcript copied into a plain directory only has a bare
    # ``.jsonl`` suffix to go on (driftshield#185). The content wins and the
    # disagreement is a warning, not a silent misparse.
    run = analyse_run(_SOURCE_FIXTURES["codex_cli"].read_bytes(), source="plain/session.jsonl")
    assert run.detected_format == "codex_cli"
    assert len(run.events) == 3
    assert any("path suggested 'claude_code'" in w for w in run.warnings)


def test_path_hint_breaks_the_tie_when_content_is_inconclusive():
    # A user record without the Claude Code envelope keys says nothing on its
    # own; the native session-store path names the format.
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})
    run = analyse_run(line, source="/home/x/.claude/projects/p/s.jsonl")
    assert run.detected_format == "claude_code"


def test_explicit_format_overrides_detection():
    run = analyse_run(_TRAJECTORY.read_bytes(), format="openclaw_trajectory")
    assert run.detected_format == "openclaw_trajectory"


def test_unknown_explicit_format_is_a_caller_error():
    with pytest.raises(UnsupportedFormatError, match="claude_code"):
        analyse_run(_TRAJECTORY.read_bytes(), format="does_not_exist")


@pytest.mark.parametrize(
    "content,reason",
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        (b'{"some": "unknown shape"}', "unrecognised_format"),
        (b"not json at all", "unrecognised_format"),
        (json.dumps([{"session_id": "x"}]).encode(), "unrecognised_format"),
        (json.dumps({"type": "summary", "sessionId": "s"}).encode(), "no_events"),
    ],
)
def test_zero_parseable_events_is_an_explicit_error(content: bytes, reason: str):
    with pytest.raises(NoParseableEventsError) as excinfo:
        analyse_run(content)
    assert excinfo.value.reason == reason


def test_parser_crash_is_reported_as_parse_failed():
    with pytest.raises(NoParseableEventsError) as excinfo:
        analyse_run(b"123\n", source="corrupt.jsonl")
    assert excinfo.value.reason == "parse_failed"
    assert "claude_code" in str(excinfo.value)


def test_unreadable_lines_are_named_in_warnings_not_dropped_silently():
    text = "banner line\n" + _CLAUDE_CODE.read_text().strip() + "\n{not json\n"
    run = analyse_run(text.encode())
    assert run.detected_format == "claude_code"
    assert "line 1: not valid JSON, skipped" in run.warnings
    assert any(w.startswith("line ") and w != "line 1: not valid JSON, skipped" for w in run.warnings)


def test_undecodable_bytes_are_replaced_and_warned():
    run = analyse_run(_CLAUDE_CODE.read_bytes() + b"\n\xff\xfe\n")
    assert any("undecodable" in w for w in run.warnings)


def test_event_sequence_input_reuses_the_same_engine():
    first = analyse_run(_CONSTRAINT_VIOLATION.read_bytes())
    again = analyse_run(first.events, run_id=first.run_id)
    assert again.detected_format == "claude_code"
    assert len(again.events) == len(first.events)
    assert [f.risks for f in again.findings] == [f.risks for f in first.findings]
    assert [h.signature_id for h in again.signature_hits] == [h.signature_id for h in first.signature_hits]
    assert again.redacted_transcript["events"]


def test_event_ids_derive_from_the_run_id():
    run_id = uuid.uuid4()
    first = analyse_run(_CLAUDE_CODE.read_bytes(), run_id=run_id)
    second = analyse_run(_CLAUDE_CODE.read_bytes(), run_id=run_id)
    assert [e.id for e in first.events] == [e.id for e in second.events]
    assert first.run_id == first.session.id == run_id
    parents = [e.parent_event_id for e in first.events if e.parent_event_id is not None]
    assert parents and all(p in {e.id for e in first.events} for p in parents)


def test_wrapper_object_with_line_records_is_a_run():
    # The pre-built envelope shape: records under ``events`` plus top-level
    # keys that must ride through to the shareable copy untouched.
    lines = [json.loads(line) for line in _CLAUDE_CODE.read_text().splitlines() if line.strip()]
    wrapper = {"events": lines, "workflow_reference": "wf-1", "session_id": "sess-1"}
    run = analyse_run(json.dumps(wrapper).encode())
    assert run.detected_format == "claude_code"
    assert run.transcript["workflow_reference"] == "wf-1"
    assert run.redacted_transcript["workflow_reference"] == "wf-1"


# --------------------------------------------------------------------------- #
# Verdict: findings and signature hits
# --------------------------------------------------------------------------- #


def test_real_aborted_run_is_unclassified_not_a_fake_match():
    run = analyse_run(_TRAJECTORY.read_bytes())
    assert run.qualification_state == "unclassified"
    assert run.signature_hits == []


def test_real_failure_run_qualifies_and_matches_with_event_references():
    run = analyse_run(_CONSTRAINT_VIOLATION.read_bytes())
    assert run.qualification_state == "qualified_failure"
    assert run.signature_hits
    hit = run.signature_hits[0]
    assert hit.signature_id.startswith("mechanism:")
    assert hit.confidence_band in {"high", "medium", "low", "very_low"}
    event_ids = {str(e.id) for e in run.events}
    assert all(ref in event_ids for ref in hit.event_ids)
    assert any(f.kind == "risk" and f.risks for f in run.findings)
    assert all(f.event_id in event_ids for f in run.findings)
    assert [f.kind for f in run.findings].count("break_point") == 1


def test_clean_run_has_no_hits():
    assert analyse_run(_CLEAN.read_bytes()).signature_hits == []


def test_trajectory_and_claude_code_tool_failure_reach_the_same_verdict():
    traj = analyse_run(_TRAJECTORY_TOOL_FAILURE)
    cc = analyse_run(_CLAUDE_CODE_TOOL_FAILURE, format="claude_code")
    assert traj.detected_format == "openclaw_trajectory"
    assert traj.qualification_state == cc.qualification_state == "qualified_failure"
    assert {h.signature_id for h in traj.signature_hits} >= {"mechanism:tool_misuse"}
    assert {h.signature_id for h in cc.signature_hits} >= {"mechanism:tool_misuse"}


def test_trajectory_abort_stays_unclassified_with_no_match():
    aborted = _trajectory(
        [
            _traj_record(4, "prompt.submitted", {"prompt": "do x"}),
            _traj_record(5, "model.completed", {"aborted": True, "error": "prompt error", "is_error": True}),
            _traj_record(6, "trace.artifacts", {"finalStatus": "error", "toolMetas": []}),
            _traj_record(7, "session.ended", {"status": "error", "error": "run aborted", "aborted": True}),
        ]
    )
    run = analyse_run(aborted)
    assert run.qualification_state == "unclassified"
    assert run.signature_hits == []


def test_signature_summary_projection_is_oss_safe():
    run = analyse_run(_CONSTRAINT_VIOLATION.read_bytes())
    summary = run.signature_summary.model_dump()
    assert summary["matches"]
    entry = summary["matches"][0]
    assert entry["match_status"] == "matched"
    assert entry["community_pack_id"] and entry["matcher_id"]
    assert set(entry) == {
        "signature_id", "signature_version", "mechanism_id", "match_status", "confidence",
        "confidence_band", "community_pack_id", "community_pack_version", "matcher_id",
        "matcher_version",
    }


# --------------------------------------------------------------------------- #
# Redaction: the derived shareable copy
# --------------------------------------------------------------------------- #


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_SNAPSHOT = json.loads((FIXTURES / "golden" / "redaction_snapshot.json").read_text())


@pytest.mark.parametrize("name", sorted(k for k in _SNAPSHOT if not k.startswith("redactor_corpus/")))
def test_redacted_transcript_is_byte_identical_to_the_snapshot(name: str):
    run = analyse_run((FIXTURES / name).read_bytes(), source=name)
    assert _canonical_hash(run.redacted_transcript) == _SNAPSHOT[name]


@pytest.mark.parametrize("name", sorted(k for k in _SNAPSHOT if k.startswith("redactor_corpus/")))
def test_redactor_corpus_output_is_byte_identical_to_the_snapshot(name: str):
    payload = json.loads((REDACTOR_CORPUS / Path(name).name).read_text())
    assert _canonical_hash(redact(payload).payload) == _SNAPSHOT[name]


def _raw_bodies(value: object) -> list[str]:
    bodies: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("content", "text", "input") and isinstance(item, str) and len(item) > 20:
                bodies.append(item)
            bodies.extend(_raw_bodies(item))
    elif isinstance(value, list):
        for item in value:
            bodies.extend(_raw_bodies(item))
    return bodies


def test_redacted_transcript_carries_no_raw_bodies_or_refused_keys():
    run = analyse_run(_CLAUDE_CODE.read_bytes())
    serialised = json.dumps(run.redacted_transcript)
    for key in ("toolUseResult", "stdout", "stderr", "error", "details", "raw"):
        assert f'"{key}"' not in serialised
    raw_bodies = _raw_bodies(run.transcript)
    assert raw_bodies
    assert not any(body in serialised for body in raw_bodies)
    assert run.redaction_manifest["entries"]


def test_redacted_transcript_reanalyses_to_the_same_classifiable_verdict():
    raw = analyse_run(_CLAUDE_CODE.read_bytes())
    redacted_lines = "\n".join(json.dumps(e) for e in raw.redacted_transcript["events"])
    again = analyse_run(redacted_lines)
    assert again.detected_format == "claude_code"
    assert again.qualification_state != "not_classifiable"
    tool_calls = lambda run: sum(1 for e in run.events if e.event_kind == "tool_call")  # noqa: E731
    assert tool_calls(again) == tool_calls(raw) > 0


def test_legacy_string_placeholder_tool_input_does_not_raise():
    entry = _cc(
        "assistant",
        [{"type": "tool_use", "id": "t", "name": "read_file", "input": "<REDACTED:tool_io:deadbeef>"}],
        "2026-07-01T00:00:00Z",
    )
    assert analyse_run(json.dumps(entry), format="claude_code").events


# --------------------------------------------------------------------------- #
# submit: visibility semantics and the redaction boundary
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, submission_id: str = "sub_1") -> None:
        class _Response:
            pass

        self.response = _Response()
        self.response.submission_id = submission_id
        self.response.processing_status = "received"
        self.server_contract_version = None


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    CliRunner().invoke(app, ["telemetry", "remote-enable", "--intake-url", _INTAKE_URL])
    return tmp_path


@pytest.fixture
def run() -> AnalysedRun:
    return analyse_run(_CLAUDE_CODE.read_bytes(), source=str(_CLAUDE_CODE))


def test_community_submit_sends_only_the_redacted_transcript(home, run, monkeypatch):
    captured = {}

    def fake_post(*, config, submission, opener=None):
        captured["config"] = config
        captured["submission"] = submission
        return _Result()

    monkeypatch.setattr("driftshield.public.post_oss_submission", fake_post)

    receipt = submit(run)

    assert receipt.visibility == "community"
    assert receipt.submission_id == "sub_1"
    envelope = captured["submission"].envelope
    expected = dict(run.redacted_transcript)
    expected["metadata"] = {"environment": "production"}
    assert envelope.payload == expected
    assert envelope.source_session_id == _CLAUDE_CODE.stem
    assert envelope.session_observed_at == run.session_observed_at
    assert envelope.signature_summary is None
    assert envelope.redaction_manifest.redaction_applied is True
    assert not any(body in json.dumps(envelope.payload) for body in _raw_bodies(run.transcript))


def test_community_submit_is_keyless(home, run):
    with pytest.raises(SubmitError, match="takes no API key"):
        submit(run, "community", "some-key")


def test_workspace_submit_requires_a_key(home, run):
    with pytest.raises(SubmitError, match="requires an API key"):
        submit(run, "workspace")


def test_unknown_visibility_is_rejected(home, run):
    with pytest.raises(SubmitError, match="community"):
        submit(run, "public")


def test_backfill_is_workspace_only(home, run):
    with pytest.raises(SubmitError, match="backfill"):
        submit(run, "community", backfill=True)


def test_workspace_submit_uses_the_authenticated_lane_with_backfill(home, run, monkeypatch):
    captured = {}

    def fake_upload(*, config, payload, workflow_reference, file_name, provenance, backfill=False):
        captured.update(
            key=config.api_key, payload=payload, backfill=backfill, provenance=provenance, file=file_name
        )
        return _Result("sub_ws")

    monkeypatch.setattr("driftshield.public.submit_teams_via_presigned_upload", fake_upload)

    receipt = submit(run, "workspace", "ws-key", backfill=True, environment="staging")

    assert receipt.visibility == "workspace" and receipt.submission_id == "sub_ws"
    assert captured["key"] == "ws-key" and captured["backfill"] is True
    assert captured["payload"]["events"] == run.redacted_transcript["events"]
    assert captured["payload"]["metadata"]["environment"] == "staging"
    assert captured["provenance"]["session_observed_at"] == run.session_observed_at.isoformat()
    assert captured["file"] == _CLAUDE_CODE.name


def test_tier_aliases_map_onto_the_two_visibilities(home, run, monkeypatch):
    monkeypatch.setattr("driftshield.public.post_oss_submission", lambda **_: _Result())
    assert submit(run, "oss").visibility == "community"
    monkeypatch.setattr(
        "driftshield.public.submit_teams_via_presigned_upload", lambda **_: _Result()
    )
    assert submit(run, "teams", "k").visibility == "workspace"


def test_large_community_submit_takes_the_presigned_lane(home, run, monkeypatch):
    captured = {}
    monkeypatch.setattr("driftshield.public.INLINE_PAYLOAD_THRESHOLD_BYTES", 1)
    monkeypatch.setattr(
        "driftshield.public.post_oss_submission",
        lambda **_: (_ for _ in ()).throw(AssertionError("inline lane must not be used")),
    )

    def fake_upload(*, config, payload, workflow_reference, file_name, provenance):
        captured["payload"] = payload
        return _Result("sub_large")

    monkeypatch.setattr("driftshield.public.submit_oss_via_presigned_upload", fake_upload)

    assert submit(run).submission_id == "sub_large"
    assert captured["payload"]["events"] == run.redacted_transcript["events"]


def test_include_analysis_attaches_the_signature_summary(home, monkeypatch):
    captured = {}

    def fake_post(*, config, submission, opener=None):
        captured["summary"] = submission.envelope.signature_summary
        return _Result()

    monkeypatch.setattr("driftshield.public.post_oss_submission", fake_post)
    failing = analyse_run(_CONSTRAINT_VIOLATION.read_bytes())

    submit(failing, include_analysis=True)

    assert captured["summary"] is not None
    assert captured["summary"].matches[0].signature_id == failing.signature_hits[0].signature_id


def test_openclaw_provenance_and_workflow_reference_come_from_the_transcript(home, monkeypatch):
    captured = {}

    def fake_post(*, config, submission, opener=None):
        captured["envelope"] = submission.envelope
        return _Result()

    monkeypatch.setattr("driftshield.public.post_oss_submission", fake_post)
    payload = json.loads(_TRAJECTORY_TOOL_FAILURE)
    payload["workflow_reference"] = "wf-from-file"
    payload["events"][0]["data"]["agentId"] = "engineering"

    submit(analyse_run(json.dumps(payload)))

    envelope = captured["envelope"]
    assert envelope.agent_id == "openclaw:engineering"
    assert envelope.model_name == "openai/gpt-5.4"
    assert envelope.workflow_reference == "wf-from-file"


def test_submit_when_remote_is_disabled_raises_before_any_network(home, run, monkeypatch):
    monkeypatch.setattr(
        "driftshield.public.post_oss_submission",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not post")),
    )
    CliRunner().invoke(app, ["telemetry", "remote-disable"])
    with pytest.raises(SubmitError, match="disabled"):
        submit(run)


def test_cli_submit_include_analysis_rides_the_door(home, monkeypatch):
    captured = {}

    def fake_post(*, config, submission, opener=None):
        captured["summary"] = submission.envelope.signature_summary
        return _Result()

    monkeypatch.setattr("driftshield.public.post_oss_submission", fake_post)

    result = CliRunner().invoke(
        app, ["submit", "--path", str(_CONSTRAINT_VIOLATION), "--include-analysis"]
    )

    assert result.exit_code == 0, result.output
    assert captured["summary"] is not None and captured["summary"].matches
