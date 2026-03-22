# OpenClaw connector mapping

This documents the first offline ingestion slice for issue #100.

## Discovery

DriftShield now proposes one connector per OpenClaw agent session directory when present under `~/.openclaw/agents/*/sessions`:

- `openclaw_main`
- `openclaw_business`
- `openclaw_engineering`

Set `OPENCLAW_HOME` to point discovery at a non-default OpenClaw home in tests or local development.

## Parser mapping

`parser_name=openclaw` maps native OpenClaw JSONL records into canonical events without reshaping upstream output.

### Supported record mappings

- `message.role=user` -> `OUTPUT` / `user_message`
- `message.role=assistant` + `content[].type=text` -> `OUTPUT` / `assistant_narrative`
- `message.role=assistant` + `content[].type=toolCall` -> `TOOL_CALL`
- `toolCall.name in {sessions_spawn, subagents}` -> `HANDOFF`
- `message.role=toolResult` -> attaches outputs back onto the originating tool call
- `custom.customType=model-snapshot` -> `BRANCH` / `model_snapshot`

### Preserved metadata

The parser keeps enough context for the next reporting slice:

- session id
- timestamps
- user vs assistant role
- tool call name and structured arguments
- tool result text, details, and error state
- handoff detection for explicit specialist spawning
- model snapshot data for provenance

## Deliberate non-goals in this slice

This change does **not** yet add:

- previous-day OpenClaw report aggregation
- reply-quality scoring vocabulary
- incremental watcher wiring
- UI reporting surfaces

Those can build on this connector and parser without changing OpenClaw transcript format.
