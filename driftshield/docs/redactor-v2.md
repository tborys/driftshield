# Recursive redactor v2

The OSS submission lane runs every payload through a recursive redactor before
posting to the intake API. Redactor v2 (driftshield#109) replaces the v1
field-name-only rule set with a depth-walking ruleset that covers tool-call
shapes, embedded secrets, and identifying paths.

## What gets redacted

The redactor applies the following rules to every value at every depth.

### Dropped keys

The following keys are removed from any object, regardless of depth, before
the rest of the rules run.

| Key | Behaviour |
|-----|-----------|
| `prompts`, `responses`, `user_identifiers` | Dropped. Public manifest claim. |
| `content`, `text` | Dropped. Nested prompt/response carriers in real session shapes. |

### Tool-IO keys (value replaced with placeholder)

Tool-call payloads are kept structurally intact so downstream analysers can
still see the shape of the call. The value at any of these keys is replaced
with `<REDACTED:tool_io:<hash>>` rather than dropped entirely.

| Key | Reason |
|-----|--------|
| `arguments`, `input`, `parameters` | Tool-call inputs may contain user data, file contents, credentials. |
| `result`, `output`, `tool_output`, `function_result` | Tool-call results may contain returned data, error traces, file contents. |
| `file_content` | Raw file contents that should never reach the intake. |
| `tool_input`, `function_args` | Tool-call inputs across frameworks. |

### Regex-detected secrets (replaced inline in any string)

The following high-confidence patterns are detected in any string value at
any depth and replaced with `<REDACTED:<category>:<hash>>` placeholders.

| Category | Pattern shape |
|----------|---------------|
| `aws_access_key` | `AKIA[0-9A-Z]{16}` |
| `github_pat` | `ghp_[A-Za-z0-9]{36}` |
| `openai_key` | `sk-[A-Za-z0-9]{20,}` |
| `jwt` | `eyJ...payload...signature` |
| `ssn` | `\d{3}-\d{2}-\d{4}` |
| `credit_card` | 13-19 digits, Luhn-validated only |

### Identifying strings (replaced inline)

| Category | Pattern shape |
|----------|---------------|
| `home_path` | `/Users/<username>`, `/home/<username>`, `C:\Users\<username>` |
| `email` | RFC-5322-light email regex |

## What does NOT get redacted

The redactor does not touch:

- Envelope metadata: `source_system`, `source_session_id`, `workflow_reference`, `project_reference`, `schema_version`, timestamps.
- Non-sensitive structural keys: `events[].type`, `events[].ts`, `tool_use[].name`, `messages[].role`, IDs that do not contain PII.
- Free-text strings that match none of the regex categories above. Free-text content not under a redacted key is passed through verbatim.

Server-side coverage for free-text content with leaked secrets that escaped
the client redactor is the job of the server-side intake backstop scanner,
not the client.

## Public manifest claim

The redaction manifest accompanying every envelope advertises only the v1
public superset (`prompts`, `responses`, `user_identifiers`). The v2 internal
ruleset is implementation-only and intentionally not surfaced on the public
contract. A future `redaction-manifest.v2` contract bump will add
`redactor_version` and `redaction_ruleset_version` fields so server-side can
identify which redactor produced a given payload.

The redactor pins both values as module-level constants:

```python
REDACTOR_VERSION = "recursive-redactor.v2.0.0"
REDACTION_RULESET_VERSION = "ruleset.v1"
```

## CLI inspection

Two flags on `driftshield telemetry submit-session` let you inspect the
redactor's behaviour without submitting:

```sh
# Print the structured list of redaction entries that would apply.
driftshield telemetry submit-session --path session.json --dry-run-redaction

# Print the manifest that would accompany the submission.
driftshield telemetry submit-session --path session.json --show-manifest
```

Both flags exit 0 without posting to the intake URL.

## Unknown shapes

The redactor was designed against six known transcript shapes: Claude Code,
Claude Desktop, Codex, OpenAI Chat Completions, LangChain, CrewAI, plus a
`generic_session` fallback keyed on a top-level `session_id` field. A payload
whose top-level shape matches none of these is refused with
`UnknownTranscriptShapeError`.

Override the refusal with `--force-unknown-shape` only if you have manually
verified that the redactor's rule set covers every sensitive position in your
payload. Silent under-redaction on unrecognised shapes is the failure mode
this gate exists to prevent.

## Adding new rules

Future phases will likely add categories. Each new rule belongs in
`src/driftshield/recursive_redactor.py` as a precompiled regex (or, for
field-name rules, a frozenset entry) and a corresponding unit test in
`tests/test_recursive_redactor.py`. Bump `REDACTION_RULESET_VERSION` whenever
the public detection surface changes.
