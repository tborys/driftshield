from __future__ import annotations

import json

from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.telemetry import TelemetryService


runner = CliRunner()


def test_telemetry_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["enabled"] is False
    assert payload["install_id"] is None

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 1
    assert "disabled" in heartbeat.stdout.lower()
    assert TelemetryService().read_events() == []


def test_telemetry_enable_registers_install_and_emits_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(app, ["telemetry", "enable"])
    assert enabled.exit_code == 0

    service = TelemetryService()
    config = service.load_config()
    assert config.enabled is True
    assert config.install_id is not None
    assert config.registered_at is not None

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 0

    events = service.read_events()
    assert [event["event_type"] for event in events] == ["registration", "heartbeat"]
    assert events[0]["payload"]["consent_state"] == "opted_in"
    assert events[1]["payload"]["status"] == "alive"


def test_emit_analysis_uses_phase_2a_metric_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    emitted = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            "matched",
            "--match-count",
            "2",
            "--primary-mechanism-id",
            "verification_failure",
        ],
    )
    assert emitted.exit_code == 0

    events = TelemetryService().read_events()
    analysis_event = events[-1]
    assert analysis_event["event_type"] == "analysis_result"
    assert analysis_event["payload"] == {
        "classifiable": True,
        "event_inventory_version": "phase-2a-v1",
        "match_count": 2,
        "mixed_mechanism": False,
        "not_classifiable_reason": None,
        "outcome_status": "matched",
        "primary_mechanism_id": "verification_failure",
    }


def test_disable_stops_further_emission(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, ["telemetry", "disable"])

    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 1

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration"]


def test_emit_analysis_rejects_invalid_outcome_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    invalid = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            "matchd",
        ],
    )

    assert invalid.exit_code == 1
    assert "outcome_status must be one of" in invalid.stdout

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration"]


def test_emit_analysis_normalizes_outcome_status_before_classifiable_check(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "enable"])

    emitted = runner.invoke(
        app,
        [
            "telemetry",
            "emit-analysis",
            "--outcome-status",
            " matched ",
            "--match-count",
            "1",
        ],
    )

    assert emitted.exit_code == 0
    analysis_event = TelemetryService().read_events()[-1]
    assert analysis_event["payload"]["outcome_status"] == "matched"
    assert analysis_event["payload"]["classifiable"] is True


_OSS_TEST_INTAKE_URL = "https://snidz3uiv5.execute-api.eu-west-2.amazonaws.com/v1/oss/submissions"


def _remote_enable_argv(*, intake_url: str = _OSS_TEST_INTAKE_URL) -> list[str]:
    return ["telemetry", "remote-enable", "--intake-url", intake_url]


def test_status_default_shows_remote_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    status = runner.invoke(app, ["telemetry", "status", "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is False
    assert payload["remote_intake_url"] is None


def test_remote_enable_persists_intake_url_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    enabled = runner.invoke(app, _remote_enable_argv())
    assert enabled.exit_code == 0
    assert _OSS_TEST_INTAKE_URL in enabled.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    # D19 contract: no legacy auth fields persisted.
    assert config.remote_api_key is None
    assert config.remote_installation_id is None

    status = runner.invoke(app, ["telemetry", "status", "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["remote_enabled"] is True
    assert payload["remote_intake_url"] == _OSS_TEST_INTAKE_URL
    # D19 status surface dropped the legacy fields.
    assert "remote_installation_id" not in payload
    assert "remote_api_key_configured" not in payload
    assert "remote_api_key" not in payload


def test_remote_enable_rejects_only_unknown_flags(tmp_path, monkeypatch):
    """D19 contract: --api-key and --installation-id are no longer accepted as flags."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    result = runner.invoke(
        app,
        [
            "telemetry",
            "remote-enable",
            "--intake-url",
            _OSS_TEST_INTAKE_URL,
            "--api-key",
            "should-be-rejected",
        ],
    )
    assert result.exit_code != 0


def test_remote_enable_migrates_away_from_d7_d8_legacy_fields(tmp_path, monkeypatch):
    """A config file from a prior D7/D8 install has remote_api_key + remote_installation_id.
    First D19 remote-enable run must clear them.
    """
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    home = tmp_path / "telemetry"
    home.mkdir(parents=True)
    (home / "config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "install_id": "uuid-old",
                "remote_intake_url": "https://example.test/v1/intake",
                "remote_api_key": "legacy-key",
                "remote_installation_id": "oss-fallback-installation",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, _remote_enable_argv())
    assert result.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.remote_api_key is None
    assert config.remote_installation_id is None
    # Local state preserved.
    assert config.enabled is True
    assert config.install_id == "uuid-old"


def test_remote_disable_clears_remote_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())

    disabled = runner.invoke(app, ["telemetry", "remote-disable"])
    assert disabled.exit_code == 0

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None
    assert config.remote_api_key is None
    assert config.remote_installation_id is None


def test_remote_enable_rejects_empty_intake_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    blank_url = runner.invoke(app, _remote_enable_argv(intake_url="   "))
    assert blank_url.exit_code == 1
    assert "intake_url" in blank_url.stdout

    config = TelemetryService().load_config()
    assert config.remote_intake_url is None


def test_local_capture_unchanged_when_remote_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, _remote_enable_argv())
    heartbeat = runner.invoke(app, ["telemetry", "heartbeat"])
    assert heartbeat.exit_code == 0

    events = TelemetryService().read_events()
    assert [event["event_type"] for event in events] == ["registration", "heartbeat"]

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL


def test_remote_enable_does_not_toggle_local_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, _remote_enable_argv())
    config = TelemetryService().load_config()
    assert config.remote_intake_url == _OSS_TEST_INTAKE_URL
    assert config.enabled is False
    assert config.install_id is None


def test_remote_disable_does_not_clear_local_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    runner.invoke(app, ["telemetry", "enable"])
    runner.invoke(app, _remote_enable_argv())

    install_id_before = TelemetryService().load_config().install_id
    runner.invoke(app, ["telemetry", "remote-disable"])

    config = TelemetryService().load_config()
    assert config.enabled is True
    assert config.install_id == install_id_before
    assert config.remote_intake_url is None


def _write_session(tmp_path, contents):
    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps(contents), encoding="utf-8")
    return session_path


def _ok_result(*, submission_id="sub_xyz", server_contract_version="phase3g.v1"):
    from driftshield.intake_contract import IntakeSubmissionResponse
    from driftshield.remote_submission import OssSubmissionResult

    return OssSubmissionResult(
        response=IntakeSubmissionResponse(
            submission_id=submission_id, processing_status="received"
        ),
        server_contract_version=server_contract_version,
    )


def test_submit_session_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {
            "session_id": "sess-1",
            "prompts": ["secret"],
            "responses": ["also secret"],
            "user_identifiers": ["alice@example.test"],
            "metadata": {"foo": "bar"},
        },
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        captured["payload_keys"] = sorted(submission.envelope.payload.keys())
        captured["request_keys"] = set(json.loads(submission.model_dump_json()).keys())
        captured["workflow_reference"] = submission.envelope.workflow_reference
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "sub_xyz" in result.stdout
    assert "received" in result.stdout
    assert captured["intake_url"] == _OSS_TEST_INTAKE_URL
    assert captured["workflow_reference"] == "default"
    assert "prompts" not in captured["payload_keys"]
    assert "responses" not in captured["payload_keys"]
    assert "user_identifiers" not in captured["payload_keys"]
    assert "metadata" in captured["payload_keys"]
    # D19 contract: request body has no installation_id, no consent_state.
    assert captured["request_keys"] == {"envelope_contract_version", "envelope"}


def test_submit_session_defaults_workflow_reference_to_default(tmp_path, monkeypatch):
    """Neither --workflow-reference nor session JSON supplies one -> 'default'."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["workflow_reference"] = submission.envelope.workflow_reference
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert captured["workflow_reference"] == "default"


def test_submit_session_prefers_session_json_workflow_reference(tmp_path, monkeypatch):
    """Session JSON's workflow_reference wins over the default when --flag absent."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {"session_id": "sess-1", "workflow_reference": "checkout-flow"},
    )
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["workflow_reference"] = submission.envelope.workflow_reference
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert captured["workflow_reference"] == "checkout-flow"


def test_submit_session_flag_overrides_session_json_workflow_reference(tmp_path, monkeypatch):
    """--workflow-reference takes precedence over session JSON's value."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {"session_id": "sess-1", "workflow_reference": "from-json"},
    )
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["workflow_reference"] = submission.envelope.workflow_reference
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--workflow-reference",
            "from-flag",
        ],
    )

    assert result.exit_code == 0
    assert captured["workflow_reference"] == "from-flag"


def test_submit_session_logs_deprecation_warning_when_server_on_phase3f_v1(
    tmp_path, monkeypatch
):
    """If the server's X-DriftShield-Contract-Version header is phase3f.v1,
    the CLI emits a deprecation note. AC5 second half."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        return _ok_result(server_contract_version="phase3f.v1")

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "deprecation" in result.stdout.lower()
    assert "phase3f.v1" in result.stdout


def test_submit_session_no_deprecation_warning_when_server_on_phase3g_v1(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        return _ok_result(server_contract_version="phase3g.v1")

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "deprecation" not in result.stdout.lower()


def test_submit_session_teams_fails_when_remote_not_configured(tmp_path, monkeypatch):
    """The baked community default is OSS-only; teams still needs remote-enable."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "ds_teams_key")
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "teams"],
    )

    assert result.exit_code == 1
    assert "not configured" in result.stdout.lower()


def test_submit_session_fails_on_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    bad_path = tmp_path / "session.json"
    bad_path.write_text("not json at all", encoding="utf-8")

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(bad_path)]
    )

    assert result.exit_code == 1
    # After the JSON-or-JSONL loader landed, the file is parsed as
    # JSONL: every line fails json.loads silently, leaving zero events.
    # Rich may wrap the error string on whitespace, so match the stable
    # prefix only.
    assert "no parseable jsonl" in result.stdout.lower()


def test_submit_session_fails_on_non_object_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    array_path = tmp_path / "session.json"
    array_path.write_text(json.dumps([{"session_id": "sess-1"}]), encoding="utf-8")

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(array_path)]
    )

    assert result.exit_code == 1
    assert "must contain a json object" in result.stdout.lower()


def test_submit_session_dry_run_redaction_prints_entries_and_does_not_submit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {
            "session_id": "sess-1",
            "events": [{"type": "user", "note": "ssn 123-45-6789"}],
        },
    )
    called = {"posted": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        called["posted"] = True

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--dry-run-redaction"],
    )

    assert result.exit_code == 0
    assert called["posted"] is False
    body = json.loads(result.stdout)
    assert body["detected_shape"] == "claude_code"
    assert any(entry["category"] == "ssn" for entry in body["entries"])


def test_submit_session_show_manifest_prints_manifest_and_does_not_submit(
    tmp_path, monkeypatch
):
    """--show-manifest must print the exact manifest shape the real
    submission path emits, so operators can preview without surprises."""
    from driftshield.intake_contract import (
        REDACTION_MANIFEST_VERSION,
        REQUIRED_REDACTION_FIELDS,
    )
    from driftshield.recursive_redactor import (
        REDACTION_RULESET_VERSION,
        REDACTOR_VERSION,
    )

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path,
        {"session_id": "sess-1", "events": []},
    )
    called = {"posted": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        called["posted"] = True

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--show-manifest"],
    )

    assert result.exit_code == 0
    assert called["posted"] is False
    manifest = json.loads(result.stdout)
    assert manifest["manifest_version"] == REDACTION_MANIFEST_VERSION == "redaction-manifest.v2"
    assert manifest["redaction_applied"] is True
    assert sorted(manifest["redacted_fields"]) == sorted(REQUIRED_REDACTION_FIELDS)
    assert manifest["redactor_version"] == REDACTOR_VERSION
    assert manifest["redaction_ruleset_version"] == REDACTION_RULESET_VERSION


def test_submit_session_show_manifest_matches_real_submission_manifest(
    tmp_path, monkeypatch
):
    """The --show-manifest output must equal the redaction_manifest the
    real builder embeds in the OSS submission request, modulo the two
    preview-only fields (detected_shape, ruleset_entry_count). Locks the
    preview against silent drift from the submission path."""
    from driftshield.remote_submission import build_oss_submission_request

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    payload = {"session_id": "sess-1", "events": []}
    session_path = _write_session(tmp_path, payload)
    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not submit")),
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--show-manifest"],
    )

    assert result.exit_code == 0
    preview = json.loads(result.stdout)
    # Strip preview-only fields before equality.
    preview.pop("detected_shape", None)
    preview.pop("ruleset_entry_count", None)

    real_request = build_oss_submission_request(
        source_session_id="sess-1", payload=payload
    )
    real_manifest = real_request.envelope.redaction_manifest.model_dump(mode="json")
    assert preview == real_manifest


def test_submit_session_refuses_unknown_shape_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"unrelated_top_key": True})

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "shape" in result.stdout.lower()


def test_submit_session_accepts_unknown_shape_when_forced(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"unrelated_top_key": True})

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        return _ok_result(submission_id="sub_forced")

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--force-unknown-shape",
        ],
    )

    assert result.exit_code == 0
    assert "sub_forced" in result.stdout


def test_submit_session_surfaces_remote_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    from driftshield.remote_submission import RemoteSubmissionError

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        raise RemoteSubmissionError("intake HTTP 422: invalid_redaction_manifest")

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission",
        fake_post,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 1
    assert "422" in result.stdout
    assert "invalid_redaction_manifest" in result.stdout


# ---------------------------------------------------------------------------
# --include-analysis flag on submit-session
# ---------------------------------------------------------------------------


def test_submit_session_default_no_signature_summary(tmp_path, monkeypatch):
    """Default invocation (no --include-analysis) keeps signature_summary=None."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["signature_summary"] = submission.envelope.signature_summary
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert captured["signature_summary"] is None


def test_submit_session_with_include_analysis_populates_signature_summary(
    tmp_path, monkeypatch
):
    """--include-analysis triggers the local matcher and attaches the block."""
    from driftshield.intake_contract import (
        SIGNATURE_SUMMARY_VERSION,
        SignatureSummary,
        SignatureSummaryEntry,
    )

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["signature_summary"] = submission.envelope.signature_summary
        return _ok_result()

    fake_summary = SignatureSummary(
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

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.build_signature_summary_from_session",
        lambda _path: fake_summary,
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--include-analysis",
        ],
    )

    assert result.exit_code == 0
    assert captured["signature_summary"] is not None
    assert captured["signature_summary"].schema_version == SIGNATURE_SUMMARY_VERSION
    assert captured["signature_summary"].matches[0].signature_id == "sig-abc"


def test_submit_session_include_analysis_strict_fail_on_builder_error(
    tmp_path, monkeypatch
):
    """--include-analysis is strict: any builder exception fails the command.

    The submission MUST NOT be sent and the exit code MUST be non-zero so the
    operator notices that the explicit opt-in could not be honoured.
    """
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})
    posted = {"called": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        posted["called"] = True
        return _ok_result()

    def boom(_path):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.build_signature_summary_from_session", boom
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--include-analysis",
        ],
    )

    assert result.exit_code != 0
    assert posted["called"] is False
    assert "build_signature_summary_from_session" in result.stderr
    assert "matcher exploded" in result.stderr


def test_submit_session_include_analysis_empty_matches_is_valid_success(
    tmp_path, monkeypatch
):
    """An empty matches list IS a valid success path under --include-analysis.

    Zero matches is not a builder failure: the submission proceeds with the
    empty SignatureSummary attached.
    """
    from driftshield.intake_contract import (
        SIGNATURE_SUMMARY_VERSION,
        SignatureSummary,
    )

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["signature_summary"] = submission.envelope.signature_summary
        return _ok_result()

    empty_summary = SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=[],
    )

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.build_signature_summary_from_session",
        lambda _path: empty_summary,
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--include-analysis",
        ],
    )

    assert result.exit_code == 0
    assert captured["signature_summary"] is not None
    assert captured["signature_summary"].schema_version == SIGNATURE_SUMMARY_VERSION
    assert captured["signature_summary"].matches == []


def test_submit_session_accepts_jsonl_input(tmp_path, monkeypatch):
    """A native JSONL transcript at --path is accepted transparently.

    The loader collects each parsed line into ``payload['events']`` and
    threads ``sessionId`` into ``payload['session_id']``.
    """
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    jsonl_path = tmp_path / "session.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "sess-jsonl",
                        "message": {"content": []},
                    }
                ),
                json.dumps({"type": "user", "message": {"content": "hi"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["payload"] = submission.envelope.payload
        captured["session_id"] = submission.envelope.source_session_id
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(jsonl_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload.get("session_id") == "sess-jsonl"
    assert isinstance(payload.get("events"), list)
    assert len(payload["events"]) == 2


# ---------------------------------------------------------------------------
# meta#273 large-upload routing (presigned S3)
# ---------------------------------------------------------------------------


def test_submit_session_large_oss_routes_to_presigned_upload(tmp_path, monkeypatch):
    """A large OSS payload skips the inline POST and uses presigned S3."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    # A big metadata blob pushes the redacted payload past the inline
    # threshold so the large-upload lane is selected.
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"blob": "x" * 300_000}}
    )

    used = {"presigned": False, "inline": False}

    def fake_presigned(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        used["presigned"] = True
        return _ok_result()

    def fake_inline(*, config, submission, opener=None):  # noqa: ARG001
        used["inline"] = True
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload",
        fake_presigned,
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_inline
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )
    assert result.exit_code == 0
    assert used["presigned"] is True
    assert used["inline"] is False


def test_submit_session_small_oss_stays_inline(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    used = {"presigned": False, "inline": False}

    def fake_presigned(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        used["presigned"] = True
        return _ok_result()

    def fake_inline(*, config, submission, opener=None):  # noqa: ARG001
        used["inline"] = True
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload",
        fake_presigned,
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_inline
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )
    assert result.exit_code == 0
    assert used["inline"] is True
    assert used["presigned"] is False


def test_submit_session_teams_tier_uses_teams_lane_with_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "ds_teams_key")
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_teams(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["api_key"] = config.api_key
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        fake_teams,
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "teams"],
    )
    assert result.exit_code == 0
    assert captured["api_key"] == "ds_teams_key"


def test_submit_session_teams_tier_without_api_key_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTSHIELD_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "teams"],
    )
    assert result.exit_code == 1
    assert "DRIFTSHIELD_API_KEY" in result.stdout


# ---------------------------------------------------------------------------
# Zero-config community lane: baked default intake URL
# ---------------------------------------------------------------------------


def test_submit_session_oss_defaults_to_community_intake_url(tmp_path, monkeypatch):
    """With no remote-enable, the OSS lane submits to the baked community URL."""
    from driftshield.telemetry import DEFAULT_COMMUNITY_INTAKE_URL

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert DEFAULT_COMMUNITY_INTAKE_URL == "https://api.driftshield.ai/v1/intake"
    assert captured["intake_url"] == DEFAULT_COMMUNITY_INTAKE_URL


def test_submit_session_oss_default_url_applies_to_presigned_lane(tmp_path, monkeypatch):
    """A large zero-config OSS payload also resolves to the baked default."""
    from driftshield.telemetry import DEFAULT_COMMUNITY_INTAKE_URL

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"blob": "x" * 300_000}}
    )

    captured = {}

    def fake_presigned(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload",
        fake_presigned,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert captured["intake_url"] == DEFAULT_COMMUNITY_INTAKE_URL


def test_submit_session_remote_enable_overrides_default_url(tmp_path, monkeypatch):
    """An explicitly configured intake URL wins over the baked default."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["intake_url"] == _OSS_TEST_INTAKE_URL


# ---------------------------------------------------------------------------
# Community opt-in declares production by default (client-side, declared)
# ---------------------------------------------------------------------------


def test_submit_session_oss_defaults_environment_to_production_inline(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["metadata"] = submission.envelope.payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "production"


def test_submit_session_oss_defaults_environment_to_production_presigned(
    tmp_path, monkeypatch
):
    """The production stamp lands before redaction, so the large lane carries it too."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"blob": "x" * 300_000}}
    )

    captured = {}

    def fake_presigned(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["metadata"] = payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload",
        fake_presigned,
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "production"


def test_submit_session_environment_flag_overrides_production_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["metadata"] = submission.envelope.payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--tier",
            "oss",
            "--environment",
            "staging",
        ],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "staging"


def test_submit_session_preserves_environment_declared_in_session_json(
    tmp_path, monkeypatch
):
    """A declared environment in the session JSON counts as the submitter
    saying otherwise; the production default must not clobber it."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"environment": "test"}}
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["metadata"] = submission.envelope.payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "test"


def test_submit_session_environment_flag_wins_over_session_json_value(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"environment": "test"}}
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["metadata"] = submission.envelope.payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--tier",
            "oss",
            "--environment",
            "demo",
        ],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "demo"


def test_submit_session_rejects_invalid_environment(tmp_path, monkeypatch):
    """An arbitrary string never rides the envelope: clean exit 1, no submission."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    submitted = {"called": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        submitted["called"] = True
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--tier",
            "oss",
            "--environment",
            "prod",
        ],
    )

    assert result.exit_code == 1
    assert "--environment must be one of" in result.stdout
    assert submitted["called"] is False


def test_submit_session_environment_flag_accepted_on_teams_tier(tmp_path, monkeypatch):
    """--environment now applies to the teams lane too (mirror of the oss lane):
    an explicit value overrides the production default and is stamped on the
    payload metadata so the hosted investigation reaches recurrence-eligibility."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "ds_teams_key")
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_teams(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["metadata"] = payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        fake_teams,
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--tier",
            "teams",
            "--environment",
            "staging",
        ],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "staging"


def test_submit_session_teams_tier_defaults_environment_to_production(tmp_path, monkeypatch):
    """A teams submission with no --environment now defaults to production
    (mirror of the oss lane), so the hosted investigation lands a declared
    production environment instead of an undeclared run."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "ds_teams_key")
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"foo": "bar"}}
    )

    captured = {}

    def fake_teams(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["metadata"] = payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        fake_teams,
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "teams"],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "production"
    # Pre-existing metadata is preserved alongside the declared environment.
    assert captured["metadata"]["foo"] == "bar"


def test_submit_session_teams_tier_keeps_environment_declared_in_session(tmp_path, monkeypatch):
    """An environment already declared in the session JSON is kept; the
    production default only fills in when none is declared (mirror of oss)."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "ds_teams_key")
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(
        tmp_path, {"session_id": "sess-1", "metadata": {"environment": "test"}}
    )

    captured = {}

    def fake_teams(*, config, payload, workflow_reference, file_name, mode="file", provenance=None, opener=None):  # noqa: ARG001
        captured["metadata"] = payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        fake_teams,
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "teams"],
    )

    assert result.exit_code == 0
    assert captured["metadata"]["environment"] == "test"


def test_community_lane_payload_classifies_production_submitter_declared(
    tmp_path, monkeypatch
):
    """End to end seam: the metadata the zero-config community lane submits
    classifies server-side as PRODUCTION with source SUBMITTER_DECLARED,
    never as a server-side silent default."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from driftshield.core.canonical_analysis import _environment_classification
    from driftshield.core.models import (
        EnvironmentClass,
        EnvironmentSource,
        Session,
        SessionStatus,
    )

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["metadata"] = submission.envelope.payload.get("metadata")
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )
    assert result.exit_code == 0

    session = Session(
        id=uuid4(),
        agent_id="claude",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
        metadata=captured["metadata"],
    )
    env_class, env_source = _environment_classification(session, None)
    assert env_class is EnvironmentClass.PRODUCTION
    assert env_source is EnvironmentSource.SUBMITTER_DECLARED


# ---------------------------------------------------------------------------
# remote-disable is an explicit opt-out: the baked default must not apply
# ---------------------------------------------------------------------------


def test_remote_disable_blocks_community_default(tmp_path, monkeypatch):
    """After remote-disable, the OSS lane has no target: the baked default
    must not resurrect remote submission behind the user's back."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "remote-disable"])
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    submitted = {"called": False}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        submitted["called"] = True
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 1
    assert "disabled" in result.stdout.lower()
    assert submitted["called"] is False


def test_remote_enable_after_disable_restores_submission(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, ["telemetry", "remote-disable"])
    runner.invoke(app, _remote_enable_argv())
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["intake_url"] = config.intake_url
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["intake_url"] == _OSS_TEST_INTAKE_URL

    config = TelemetryService().load_config()
    assert config.remote_opt_out is False


def test_status_reports_effective_oss_intake_url(tmp_path, monkeypatch):
    """status must reflect what an OSS submit will actually do in all three
    states: zero-config (baked default), opted out (null), configured."""
    from driftshield.telemetry import DEFAULT_COMMUNITY_INTAKE_URL

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))

    fresh = json.loads(runner.invoke(app, ["telemetry", "status", "--json"]).stdout)
    assert fresh["remote_opt_out"] is False
    assert fresh["effective_oss_intake_url"] == DEFAULT_COMMUNITY_INTAKE_URL

    runner.invoke(app, ["telemetry", "remote-disable"])
    disabled = json.loads(runner.invoke(app, ["telemetry", "status", "--json"]).stdout)
    assert disabled["remote_opt_out"] is True
    assert disabled["effective_oss_intake_url"] is None

    runner.invoke(app, _remote_enable_argv())
    enabled = json.loads(runner.invoke(app, ["telemetry", "status", "--json"]).stdout)
    assert enabled["remote_opt_out"] is False
    assert enabled["effective_oss_intake_url"] == _OSS_TEST_INTAKE_URL


def test_zero_config_inline_oss_posts_to_live_oss_route(tmp_path, monkeypatch):
    """End to end through the real transport seam: zero-config community
    opt-in must POST the inline envelope to the unauthenticated OSS route
    derived from the baked canonical base, never to /v1/intake verbatim
    (which 422s on unauthenticated inline submits)."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    captured = {}

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        return _FakeResp(
            json.dumps(
                {"submission_id": "sub_abc", "processing_status": "received"}
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        "driftshield.remote_submission.request.urlopen", fake_urlopen
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["url"] == "https://api.driftshield.ai/v1/oss/submissions"
    assert "X-api-key" not in captured["headers"]


def test_submit_session_openclaw_trajectory_stamps_real_provenance(
    tmp_path, monkeypatch
):
    """An OpenClaw trajectory submitted with no provenance flags carries the
    harness/agent and driving provider/model derived from the trajectory."""
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    event = {
        "type": "session.started",
        "runId": "run-1",
        "traceId": "trace-1",
        "schemaVersion": 1,
        "seq": 1,
        "source": "runtime",
        "provider": "openai-codex",
        "modelId": "gpt-5.4",
        "data": {"agentId": "engineering"},
    }
    session_path = _write_session(
        tmp_path, {"session_id": "sess-oc", "events": [event]}
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["agent_id"] = submission.envelope.agent_id
        captured["model_name"] = submission.envelope.model_name
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        ["telemetry", "submit-session", "--path", str(session_path), "--tier", "oss"],
    )

    assert result.exit_code == 0
    assert captured["agent_id"] == "openclaw:engineering"
    assert captured["model_name"] == "openai-codex/gpt-5.4"


def test_submit_session_explicit_provenance_flags_win_over_derived(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    event = {
        "type": "session.started",
        "runId": "run-1",
        "traceId": "trace-1",
        "schemaVersion": 1,
        "seq": 1,
        "source": "runtime",
        "provider": "openai-codex",
        "modelId": "gpt-5.4",
        "data": {"agentId": "engineering"},
    }
    session_path = _write_session(
        tmp_path, {"session_id": "sess-oc", "events": [event]}
    )

    captured = {}

    def fake_post(*, config, submission, opener=None):  # noqa: ARG001
        captured["agent_id"] = submission.envelope.agent_id
        captured["model_name"] = submission.envelope.model_name
        return _ok_result()

    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app,
        [
            "telemetry",
            "submit-session",
            "--path",
            str(session_path),
            "--tier",
            "oss",
            "--agent-id",
            "my-agent",
            "--model-name",
            "my-model",
        ],
    )

    assert result.exit_code == 0
    assert captured["agent_id"] == "my-agent"
    assert captured["model_name"] == "my-model"
