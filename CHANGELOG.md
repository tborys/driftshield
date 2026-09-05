# Changelog

All notable changes to `driftshield` are recorded here. The GitHub release
notes for each tag are taken from the matching section of this file.

## 0.2.1 - 2026-09-05

### A tool error never recovered before the session ends is a failure

A run whose last tool call reported an error, with no later tool call
completing, now qualifies as a failure. Before this release such a run was
`unclassified` with `no_material_delta_detected` unless a risk detector also
fired, which on coding agent sessions such as Claude Code it rarely did, so a
session that died on a failed command looked the same as a successful one.

- `qualification_state` is `qualified_failure` with the reason
  `unrecovered_tool_error_at_session_end`, and the expected versus actual
  delta carries the same delta type.
- The candidate break point is that final failed tool call, so `analyze` and
  `report` point at the call that ended the run.
- A tool error a later completed tool call recovered is still not a failure.

Verdicts change for affected runs, so re-analyse anything you compare across
versions.

## 0.2.0 - 2026-08-27

First published release on PyPI, as `driftshield-sdk`. Earlier versions were
never published, so everything below is what you get when you install it for
the first time.

The distribution is `driftshield-sdk` rather than `driftshield` because PyPI
rejected the shorter name: it strips separators when checking for collisions,
and an unrelated project called `drift-shield` has held the name since 2024.
Nothing else changes. You install `driftshield-sdk`, you `import driftshield`
and the command is still `driftshield`.

```bash
pip install driftshield-sdk
```

### The public API is two calls

The `driftshield` package now has one door: `analyse_run` and `submit`.
Everything else in the package (parsers, format detection, redaction,
signature matching, transport) is internal and can change without notice.

```python
from driftshield import analyse_run, submit

run = analyse_run(open("session.jsonl", "rb").read(), source="session.jsonl")
receipt = submit(run)  # community lane, redacted, no key needed
```

- `analyse_run(content, *, source=None, format=None, run_id=None)` analyses one
  agent run and returns an `AnalysedRun`: the parsed events, the findings
  anchored to events, community signature hits, the qualification verdict,
  the redacted transcript and any warnings. It touches no network, database
  or filesystem.
- Supported inputs: Claude Code, Codex CLI, OpenClaw session and trajectory
  JSONL; Claude Desktop, Codex Desktop, CrewAI and LangChain single document
  JSON; and a wrapper object with the records under `"events"`. Detection is
  content first. A path is only a hint and the content wins when they
  disagree.
- Parsing is best effort. Lines that cannot be read are skipped and named in
  `run.warnings` (for example `line 12: not valid JSON, skipped`). Zero
  parseable events is an error, `NoParseableEventsError`, never an empty
  success. `.reason` tells you whether the content was empty, unrecognised,
  failed to parse or yielded no events.
- Redaction happens at the share boundary. `run.redacted_transcript` is
  exactly what a submission sends; nothing leaves the machine until you call
  `submit`.
- `submit(run, visibility="community", key=None, **options)` sends the
  redacted transcript. `"community"` (the default) needs no key and lands in
  the public community dataset. `"workspace"` needs your workspace API key and
  lands in your private workspace. The CLI's `--tier oss` and `--tier teams`
  are aliases for the two lanes.
- Every CLI command (`analyze`, `batch`, `submit`, `report`, `inspect`,
  `ingest`), the self hosted `/api/ingest` route and the connector watcher go
  through the same two calls, so they agree on formats, warnings and
  redaction.

Full reference: `docs/public-api.md`.

### CLI

- `driftshield batch <dir-or-archive>` analyses every transcript in a
  directory, `.zip` or `.tar.gz`, with per file outcomes and a stable `--json`
  summary. `--submit` submits each run; `--backfill` marks workspace
  submissions as post hoc imports so they index at their original time;
  `--workflow-reference` sets or derives the workflow per source.
- `driftshield submit` is the upload path for hosted analysis, with
  `--environment` (`production`, `staging`, `test`, `demo`), `--agent-id`,
  `--model-name`, `--model-version` and `--show-manifest` to print the
  redaction manifest before anything is sent.
- `driftshield --version` reports the installed version, and so does
  `GET /api/health` on a self hosted instance.

### Fixes

- Redaction is linear time on large transcripts. Email redaction previously
  backtracked quadratically, so big runs could take minutes or appear to hang.
- Batch mode detects the format from content before trusting a path hint.
  A `.jsonl` file that parsed to zero events under the hinted parser is now
  re-detected instead of being reported as empty.
- Self hosted ingest (`POST /api/ingest`) accepts `format=auto` and every
  supported transcript shape, including the OpenClaw trajectory wrapper, in
  line with the CLI.
- Redaction keeps message content analysable instead of dropping it
  wholesale, so submitted runs no longer degrade to zero tool calls. Nested
  structures are traversed rather than discarded.
- Signature matching covers the first wave of community failure families and
  surfaces genuine tool failures in agent trajectories.

### Breaking changes

The public surface was consolidated into `analyse_run` and `submit`. The
following importable names were removed. None of them had been published on
PyPI, but if you were installing from source they no longer exist.

| Removed | Use instead |
|---------|-------------|
| `driftshield.public.analyse` | `driftshield.analyse_run` (returns `AnalysedRun` instead of a dict) |
| `driftshield.public.detect_source` | `analyse_run(...).detected_format` |
| `driftshield.public.ANALYSE_SCHEMA_VERSION` | Removed; the return type is the contract |
| `driftshield.cli.parsers` (`detect_parser`, `get_parser`, `ParserNotFoundError`) | `analyse_run(content, format=...)`; unknown names raise `UnsupportedFormatError` |
| `driftshield.cli._session_payload.load_session_payload` | `analyse_run(open(path, "rb").read(), source=str(path))` |
| `driftshield.cli._signature_summary` (`build_signature_summary_from_match`, `build_signature_summary_from_session`) | `AnalysedRun.signature_hits` and `AnalysedRun.signature_summary` |
| `driftshield.cli._submit` (`submit_session_core`, `SubmitOutcome`, `SubmitCoreError`, `IncludeAnalysisError`) | `driftshield.submit` returning `SubmitReceipt`; errors are `SubmitError` |
| `driftshield.remote_submission` (`build_redacted_payload`, `redact_payload`, `redact_payload_with_manifest`, `detect_shape`, `derive_openclaw_provenance`, `UnknownTranscriptShapeError`) | `AnalysedRun.redacted_transcript`; `submit` reads agent and model from the run |
| `driftshield.api.ingest_workflow.resolve_format` | Internal to `/api/ingest`; use `analyse_run(..., format=...)` |
| `driftshield.db.persistence.IngestProvenance` | Internal; provenance is carried on `AnalysedRun` |
| `driftshield.parsers.openclaw_trajectory.unwrap_trajectory_wrapper` | `analyse_run` unwraps the trajectory wrapper itself |

Behaviour changes to be aware of:

- Zero parseable events now raises `NoParseableEventsError` everywhere (CLI,
  API and library). Previously some paths returned an empty result.
- `submit` never retries. A transport failure raises `SubmitError` with the
  HTTP status and body.
- A key on the community lane, or no key on the workspace lane, is an error
  rather than a silent fallback.
