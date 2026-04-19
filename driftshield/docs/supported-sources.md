# Supported local transcript sources

| Source | Discovery candidate | One-shot ingest | Watch support | Notes |
| --- | --- | --- | --- | --- |
| Claude Code | Yes | Yes | Yes | Project-scoped discovery under `~/.claude/projects/<project-key>`. Existing behaviour kept stable. |
| Claude Desktop | Yes | Yes | Best-effort | DriftShield now looks for local artefacts under `~/.claude-desktop/sessions/`. Format support is currently bounded to the representative message/tool-call JSON shape covered by fixtures. |
| Codex CLI | Yes | Yes | Best-effort | DriftShield now looks for local artefacts under `~/.codex/sessions/`. JSONL sessions with message and tool-call records are supported in this slice. |
| Codex Desktop | Yes | Yes | Best-effort | DriftShield now looks for local artefacts under `~/.codex-desktop/sessions/`. JSON sessions with message arrays are supported in this slice. |
| LangChain / LangSmith export JSON | No | Yes | No | Manual ingest via `--parser langchain`. Supported scope is bounded to exported run JSON with `inputs.messages`, `outputs.messages`, and tool child runs. |
| OpenClaw agents | Yes | Yes | Yes | Existing OpenClaw session connectors remain unchanged. |

## Provenance

Session APIs expose a `provenance.source_type` field derived from the persisted parser version, alongside `source_session_id`, `source_path`, and `ingested_at`, so the UI can distinguish Claude Code, Claude Desktop, Codex CLI, and Codex Desktop sessions.

## Current limits

- Desktop/Codex watchability is best-effort because upstream tools do not yet provide a formally versioned transcript contract.
- If a source emits a different local schema, ingestion falls back to manual fixture-driven parser extension rather than claiming generic support.
