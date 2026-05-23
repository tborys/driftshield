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
        "driftshield.cli.commands.telemetry.post_oss_submission",
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
    )

    assert result.exit_code == 0
    assert "deprecation" not in result.stdout.lower()


def test_submit_session_fails_when_remote_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    session_path = _write_session(tmp_path, {"session_id": "sess-1"})

    result = runner.invoke(
        app, ["telemetry", "submit-session", "--path", str(session_path)]
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission",
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission",
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.build_signature_summary_from_session",
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.build_signature_summary_from_session", boom
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
    )
    monkeypatch.setattr(
        "driftshield.cli.commands.telemetry.build_signature_summary_from_session",
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
        "driftshield.cli.commands.telemetry.post_oss_submission", fake_post
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
