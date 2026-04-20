# Phase 2a Telemetry

DriftShield Phase 2a telemetry is explicitly opt-in and disabled by default.

The current OSS transport is intentionally simple:

- registration, heartbeat, and sample analysis-result events are written only after opt-in
- events are appended to a local NDJSON stream under `DRIFTSHIELD_HOME/telemetry/` or `~/.driftshield/telemetry/`
- this keeps the consent boundary, event inventory, and smoke path testable before broader instrumentation lands

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

Used as the Phase 2a smoke path for metric-shaped event fields before full instrumentation in `driftshield-meta#33`.

Fields:

- `event_type = analysis_result`
- `occurred_at`
- `install_id`
- `payload.outcome_status`
- `payload.classifiable`
- `payload.match_count`
- `payload.primary_family_id`
- `payload.mixed_family`
- `payload.not_classifiable_reason`
- `payload.event_inventory_version = phase-2a-v1`

These fields intentionally mirror the required run-level inventory from `driftshield-meta/docs/phases/phase-2a/metrics-semantics-v1.md` without adding broader product analytics.

## CLI smoke path

```bash
# show current consent state
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry status

# opt in and register this install
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry enable

# emit one heartbeat
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry heartbeat

# emit one sample analysis-result event
DRIFTSHIELD_HOME=/tmp/driftshield driftshield telemetry emit-analysis \
  --outcome-status matched \
  --match-count 1 \
  --primary-family-id coverage_gap
```

## Out of scope for Phase 2a

- background emission without explicit consent
- remote collection transport
- growth analytics, user analytics, or marketing telemetry
- full product instrumentation beyond the minimum metrics semantics
