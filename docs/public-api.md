# DriftShield public API

DriftShield's engine has two public operations. Everything else in the
`driftshield` package (format detection, parsers, redaction, signature
evaluation, transport) is internal and can change without notice.

```python
from driftshield import analyse_run, submit

run = analyse_run(open("session.jsonl", "rb").read(), source="session.jsonl")
receipt = submit(run)  # community lane, redacted, no key
```

Both calls are synchronous. `analyse_run` touches no network, database or
filesystem; `submit` is the only call that sends anything off the machine.

## `analyse_run(content, *, source=None, format=None, run_id=None) -> AnalysedRun`

Analyse one agent run.

| Argument | Meaning |
|----------|---------|
| `content` | The raw transcript as `bytes` or `str`, or an already parsed event sequence (for example `run.events` from an earlier call). |
| `source` | Optional provenance label, usually the file path. Only a hint for format detection; the content decides. Also recorded on the run and used as the upload file name. |
| `format` | Force a parser instead of detecting one: `claude_code`, `claude_desktop`, `codex_cli`, `codex_desktop`, `crewai`, `langchain`, `openclaw`, `openclaw_trajectory`. |
| `run_id` | Fix the run identity (a `uuid.UUID`). Event ids derive from it, so the same content with the same `run_id` always yields the same ids. |

Supported inputs: native Claude Code, Codex CLI, OpenClaw session and
trajectory JSONL; Claude Desktop, Codex Desktop, CrewAI and LangChain single
document JSON; and a wrapper object with the records under `"events"`.
Detection is content first. A path hint only breaks ties when the content is
inconclusive; when the two disagree the content wins and a warning says so.

Analysis is best effort. Lines that cannot be read are skipped and named in
`run.warnings`; they never fail the run silently.

### `AnalysedRun`

The result. Local only; nothing in it leaves the machine until `submit`.

| Field | Meaning |
|-------|---------|
| `events` | The parsed run in full detail (`CanonicalEvent` objects, in order). |
| `findings` | What went wrong, anchored to events. Each `Finding` has `kind` (`"risk"` for a flagged event, `"break_point"` for the identified inflection), `event_index`, `event_id`, `risks` (flag names) and `summary`. |
| `signature_hits` | Community signatures the deterministic matcher matched. Each `SignatureHit` has `signature_id`, `mechanism_id`, `confidence`, `confidence_band` (`high`, `medium`, `low`, `very_low`), `summary` and `event_ids`. |
| `qualification_state` | The verdict: `qualified_failure`, `unclassified` or `not_classifiable`, with `qualification_reasons` alongside. A run qualifies when a risk detector flagged a step, or when the session ended on a tool call that reported an error and no later tool call completed (reason `unrecovered_tool_error_at_session_end`). A tool error a later completed tool call recovered is not a failure. |
| `redacted_transcript` | The shareable copy, derived from the transcript by the redactor. This is exactly what a community submission sends. |
| `source` | The `source` you passed, or `None`. |
| `detected_format` | The parser that read the run (one of the names above, or `"events"` for an event sequence with no parser provenance). |
| `warnings` | Exactly what could not be read and why, for example `line 12: not valid JSON, skipped`. Empty when everything parsed. |

Convenience properties: `session_observed_at` (the last event's timestamp,
the run's own end time) and `signature_summary` (the hits in the shape a
submission envelope carries). Other attributes on the object are engine
detail for DriftShield's own CLI and API and are not part of the contract.

### Errors

| Error | When |
|-------|------|
| `UnsupportedFormatError` | `format` names a parser DriftShield does not have. A caller error; the message lists the available names. |
| `NoParseableEventsError` | Not a single event could be read. `.reason` is `empty` (blank content), `unrecognised_format` (no parser matches and no path hint helps), `parse_failed` (the parser raised on the content) or `no_events` (a recognised format that yielded nothing). `.warnings` carries what was learned before giving up. |

Both subclass `ValueError`. Zero parseable events is always an error, never
an empty success.

## `submit(run, visibility="community", key=None, **options) -> SubmitReceipt`

Send a run's redacted transcript to DriftShield.

| Visibility | Key | What is sent | Where it lands |
|------------|-----|--------------|----------------|
| `"community"` (default) | None. Passing one is an error. | `run.redacted_transcript` | The public community dataset. |
| `"workspace"` | Required: the workspace API key. | `run.redacted_transcript` | Your private workspace. Whether the workspace keeps redacted or fuller detail is a setting the workspace admin controls on the server; there is no per call flag. |

The CLI's `--tier oss` and `--tier teams` are aliases for `community` and
`workspace`.

Options, all keyword only and optional: `source_session_id` (defaults to the
`source` file stem), `workflow_reference` (defaults to a `workflow_reference`
key in the transcript, then `"default"`), `project_reference`,
`source_report_id`, `agent_id`, `model_name`, `model_version` (for OpenClaw
trajectories the agent and model are read from the run when not given),
`environment` (`production`, the default, or `staging`, `test`, `demo`),
`backfill` (workspace only; index on the run's own timestamps rather than
arrival time) and `include_analysis` (attach `run.signature_summary` to the
envelope).

The intake URL comes from the local DriftShield configuration
(`driftshield telemetry remote-enable --intake-url URL`); the community lane
has a built in default and `telemetry remote-disable` switches submission off.

### `SubmitReceipt`

`submission_id`, `processing_status`, `visibility` (the resolved lane),
`server_contract_version` and `deprecation_warning` (set when the server
advertises a different contract version than this client; the submission was
still accepted).

### Errors

`SubmitError` for anything that stops the submission: an unknown visibility, a
key on the community lane or a missing key on the workspace lane, `backfill`
outside the workspace lane, an invalid `environment`, submission disabled or
not configured, or a transport failure (the message carries the HTTP status
and body, or the unreachable reason). Nothing is retried.

## Command line

The CLI is a thin skin over the same two calls: `driftshield analyze <path>`,
`driftshield batch <dir-or-archive>` (analyse every file, `--submit` to
submit each one) and `driftshield submit --path <file>`. `driftshield report`,
`inspect` and `ingest` also analyse through `analyse_run`.
