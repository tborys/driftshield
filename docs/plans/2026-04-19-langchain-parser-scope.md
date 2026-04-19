# LangChain parser scope for issue #11

Issue: `tborys/driftshield#11`  
Meta reference: `tborys/driftshield-meta#22`

## Why this spec exists

The current repo has a clear parser protocol and representative fixtures for Claude, Codex, and OpenClaw sources, but it does **not** yet contain a canonical LangChain transcript fixture or a repo-local statement of which LangChain export shape should be supported first.

Without that decision, implementing `#11` would mean guessing the input contract and risking a parser that is technically valid but aimed at the wrong artifact.

This note narrows the first supported slice so `#11` becomes agent-executable.

## First supported input shape

Support **one** LangChain trace shape first:

- **source**: LangSmith / LangChain exported run JSON
- **format**: a single JSON object or JSON array containing run records
- **minimum fields expected from the exported run data**:
  - `id`
  - `name`
  - `run_type`
  - `start_time`
  - `end_time` when available
  - `inputs`
  - `outputs`
  - `error`
  - `parent_run_id` when child runs are present

This matches the public LangSmith run data shape closely enough to be realistic while keeping the first implementation bounded.

## Explicitly out of scope for issue #11

- direct ingestion from live LangSmith APIs
- every historical LangChain callback format
- LangGraph state dumps
- arbitrary user-defined trace serialisations
- streaming event reconstruction beyond what is present in the exported run JSON
- support for multiple incompatible LangChain export shapes in one pass

## Parsing contract for the first slice

The first implementation for `#11` should:

1. accept a representative exported LangSmith/LangChain run fixture
2. reconstruct a stable session id from `trace_id` or root `id`
3. map user/model message content from `inputs.messages` and `outputs.messages` when present
4. map tool runs or child runs with `run_type == "tool"` into `EventType.TOOL_CALL`
5. preserve ordering using execution order if present, otherwise start time order
6. surface failed child runs via metadata and output fields rather than dropping them silently
7. preserve enough structure for later graph and failure analysis work without trying to solve the full forensic object model inside this parser

## Recommended canonical event mapping

### Session identity

- `session_id` -> `trace_id` if present, else root `id`
- parser `source_type` -> `langchain`
- default agent id -> `langchain`

### User input

If `inputs.messages` contains user messages, emit `EventType.OUTPUT` events with:

- `agent_id = "user"`
- `action = "user_message"`
- `metadata.semantic_action_category = "user_input"`

### Model output

If `outputs.messages` contains assistant messages, emit `EventType.OUTPUT` events with:

- `agent_id = "langchain"`
- `action = "assistant_narrative"`
- `metadata.semantic_action_category = "reasoning"`

### Tool execution

If a run or child run has `run_type == "tool"`, emit `EventType.TOOL_CALL` with:

- `action` from the tool run `name`
- `inputs` from the tool run `inputs`
- `outputs.result` from the tool run `outputs`
- `metadata.raw_action` from the tool run `name`
- `metadata.semantic_action_category = "other"` unless a clearer category mapping is obvious and low risk

### Failure context

If a run has `error`, preserve it in the emitted event `outputs` or `metadata` so the failure location is not lost.

## Fixture requirement

Before or alongside implementation, add one representative LangChain fixture under:

- `driftshield/tests/fixtures/transcripts/`

The fixture should cover at least:

- one user message
- one model response
- one tool child run
- one stable timestamp path
- one explicit parent/child relationship

A second fixture for an errored run is useful but not required for the first PR.

## Validation requirement

The implementation PR for `#11` should include:

- parser unit tests for the representative fixture
- parser registry coverage for `get_parser("langchain")`
- parser auto-detection rules only if a deterministic local file/path rule exists
- a smoke ingest or analyse path using the fixture

## Follow-on note

If this scope is accepted, the next PR for `#11` should be a normal implementation PR in `tborys/driftshield` with:

- `src/driftshield/parsers/langchain.py`
- parser registry wiring
- fixture(s)
- tests
- minimal user-facing doc update
