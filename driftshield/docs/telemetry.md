# Telemetry

DriftShield telemetry is explicitly opt-in and disabled by default.

The current OSS transport is intentionally simple:

- registration, heartbeat, and sample analysis-result events are written only after opt-in
- events are appended to a local NDJSON stream under `DRIFTSHIELD_HOME/telemetry/` or `~/.driftshield/telemetry/`
- this keeps the consent boundary, event inventory, and smoke path testable before broader instrumentation lands

Uploading a session for hosted investigation is a separate action. Use `driftshield submit`
for that. Telemetry opt-in does not trigger or gate uploads.

## Consent boundary

- default state: disabled
- enabling telemetry creates a local install id and records one `registration` event
- disabling telemetry stops all further event emission but preserves the install id for later re-enablement
- heartbeat and analysis-result emission return no-op behaviour when telemetry is disabled

## Event inventory

### Registration

Emitted once on first opt-in.

Fields:

- `event_type = registration`
- `occurred_at`
- `install_id`
- `payload.consent_state = opted_in`
- `payload.event_inventory_version = phase-2a-v1`

### Heartbeat

Emitted only when telemetry is enabled and the operator explicitly triggers a heartbeat.

Fields:

- `event_type = heartbeat`
- `occurred_at`
- `install_id`
- `payload.status = alive`
- `payload.event_inventory_version = phase-2a-v1`

### Analysis result

Used as the smoke path for metric-shaped event fields before broader product instrumentation lands. When telemetry opt-in is enabled, the OSS ingest path now emits this event automatically for newly analysed runs.

Fields:

- `event_type = analysis_result`
- `occurred_at`
- `install_id`
- `payload.outcome_status`
- `payload.classifiable`
- `payload.match_count`
- `payload.primary_mechanism_id`
- `payload.mixed_mechanism`
- `payload.not_classifiable_reason`
- `payload.event_inventory_version = phase-2a-v1`

These fields intentionally mirror the required run-level inventory for outcome status, classifiability, match count, mechanism rollup, and not-classifiable reasons without adding broader product analytics.

Current OSS emission path:

- the `driftshield telemetry emit-analysis` command remains available for smoke testing
- the `/api/ingest` flow now emits one `analysis_result` event for newly analysed runs when telemetry is enabled
- deduplicated re-ingest responses do not emit a second `analysis_result` event

## CLI reference

```bash
# show current consent state
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry status

# opt in and register this install
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry enable

# opt out
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry disable

# emit one heartbeat
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry heartbeat

# emit one sample analysis-result event
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry emit-analysis \
  --outcome-status matched \
  --match-count 1 \
  --primary-mechanism-id coverage_gap

# configure or clear the OSS intake URL override
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry remote-enable --intake-url <url>
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry remote-disable
```

## Uploading sessions

Uploading a session to DriftShield for hosted investigation is done with `driftshield submit`,
not via the telemetry commands. The client redacts the transcript locally before upload.

OSS community lane:

```bash
driftshield submit --path <session.json>
```

Teams lane (requires `DRIFTSHIELD_API_KEY`):

```bash
DRIFTSHIELD_API_KEY=... driftshield submit --path <session.json> --tier teams
```

Pass `--include-analysis` to attach the local matcher verdict to the submission.

## Out of scope

- background emission without explicit consent
- remote collection transport
- growth analytics, user analytics, or marketing telemetry
- full product instrumentation beyond the minimum metrics semantics
