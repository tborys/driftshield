# Changelog

## v0.2.0 — first PyPI release (unreleased)

First published release of `driftshield`. Everything below is on `main` and
ships together; earlier versions were never published.

### CLI

- `driftshield submit` is the canonical upload path for hosted analysis (#153),
  with the teams tier defaulting to the production environment and an
  `--environment` override (#154).
- Batch analyse mode: run the full analyse + redact + submit pipeline over a
  directory or archive (.zip / .tar.gz) of transcripts, with per-file outcomes
  and a stable JSON summary (#163).
- `--backfill` marks batch submissions as post-hoc imports so historical
  sessions index at their original observation time, including
  `session_observed_at` on every envelope (#169, #174).
- New submission metadata flags: `--agent-id`, `--model-name`,
  `--model-version` (#112).
- `--show-manifest` reports the exact redaction manifest that would be
  submitted (#112).

### Envelope and API

- Submission envelope upgraded to `phase3g.v1`; the server keeps accepting the
  previous envelope during a deprecation window and the CLI now parses
  deprecation response headers and warns before the window closes (#112).
- Content-based `analyse()` public entrypoint returning the full verdict for
  programmatic use (#149).

### Redaction

- Recursive redactor v2: nested structures are traversed instead of dropped.
- Redaction keeps message content analysable instead of dropping it wholesale,
  so hosted submissions no longer degrade to zero tool calls (#158).
- Manifest provenance: submissions carry a truthful record of which redaction
  pass produced them.

### Analysis

- Broadened first-wave signature localisation (#155).
- Agent trajectory tool failures are surfaced so genuine failures qualify for
  matching (#150).

### Tooling

- `scripts/dev-verify.sh` mirrors the four required CI checks (#161).
