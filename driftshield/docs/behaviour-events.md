# Phase 3e behaviour events

This is the OSS-safe v1 behaviour-event layer for intelligence surfaces.

It is **not** the older generic telemetry work from `#15` / `#17`.

## Separate from telemetry

Telemetry remains the opt-in local NDJSON stream for registration, heartbeat, and analysis-result smoke-path events.

Behaviour events are different:

- they model explicit intelligence-surface subjects
- they record user interaction with trusted intelligence surfaces
- they make bounded pattern-to-action proxy metrics computable later
- they can work even when generic telemetry is disabled

## V1 subject model

Each subject persists:

- `subject_id`
- `subject_type` = `trusted_pattern | report | linked_run_set`
- `session_id` when the subject came from a specific investigated run
- `pattern_reference`
- `trust_band`
- `surface` = `api | ui | report`
- `first_exposed_at`

## V1 event model

Each event persists:

- `event_id`
- `occurred_at`
- `event_type`
- `subject_id`
- `actor_id` where available
- `originating_session_id` where applicable
- `metadata_json`

Supported v1 event types:

- `pattern_viewed`
- `pattern_expanded`
- `pattern_revisited`
- `pattern_linked_runs_viewed`
- `new_run_after_pattern_view`

## Follow-up linkage

For trusted pattern subjects, OSS v1 can automatically attach `new_run_after_pattern_view` when a later run is ingested within the default 24-hour window and can be linked by the available local actor surrogate.

This remains an observable behaviour signal, not a confirmed outcome metric.
