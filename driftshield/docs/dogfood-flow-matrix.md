# Dogfood flow test matrix

This matrix defines the practical end-to-end dogfood loop we expect to keep stable in CI.
It favours deterministic API and service seams over brittle browser automation.

## Coverage goals

| Flow | Expected behaviour | CI coverage |
| --- | --- | --- |
| First-run discovery | Proposed connector is found without scanning transcript contents | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/api/test_connectors.py::test_connector_discovery_approve_and_rescan_flow` |
| Discovery deny / approve / re-scan | Denied connectors stay blocked until explicit approval; approved connectors can re-scan deterministically | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/db/test_connectors.py::test_connector_supports_deny_pause_disconnect_and_reapprove` |
| One-shot ingest | Approved connector can ingest the latest transcript from a clean state | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/cli/test_connectors.py::test_connectors_cli_discovery_and_rescan_flow` |
| Incremental watcher ingest | New transcript activity is picked up without duplicating sessions or nodes | `tests/db/test_connector_watcher.py::test_watcher_incrementally_updates_existing_session_without_duplicates` |
| Watch restart recovery | Paused watcher does not ingest new data; resumed watcher catches up on restart | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/db/test_connector_watcher.py::test_watcher_respects_pause_resume_and_restart_recovery` |
| Partial write recovery | Half-written transcript lines do not create duplicate nodes or poison state | `tests/db/test_connector_watcher.py::test_watcher_handles_partial_reads_without_duplicate_nodes` |
| Review path for a flagged session | A flagged session appears in the session list, exposes graph risk flags, and accepts a review outcome via the API | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/api/test_sessions.py::test_create_session_validation_and_list_for_node`, `tests/api/test_validations.py::test_create_and_list_validations` |
| Pause / disconnect / reconnect | Connector can pause, disconnect, and re-approve cleanly | `tests/api/test_dogfood_flow_matrix.py::test_dogfood_flow_matrix_smoke`, `tests/db/test_connectors.py::test_connector_supports_deny_pause_disconnect_and_reapprove` |

## Deterministic fixture shape

The smoke flow uses a minimal Claude transcript where a tool input contains three sections and the tool result returns two reviewed sections. That intentionally produces a `coverage_gap` flag, which gives us a stable flagged session for review-path assertions.

## Local verification

Run the focused dogfood suite:

```bash
pytest \
  driftshield/tests/api/test_dogfood_flow_matrix.py \
  driftshield/tests/api/test_connectors.py \
  driftshield/tests/api/test_sessions.py \
  driftshield/tests/api/test_validations.py \
  driftshield/tests/db/test_connectors.py \
  driftshield/tests/db/test_connector_watcher.py
```

## Manual validation still worth doing

These are intentionally left out of CI for now:

- Visual review of the in-app drawer layout and copy.
- Browser-level confirmation that the session list, graph panel, and review drawer feel coherent together.
- Long-running file watcher behaviour against live local transcript churn rather than deterministic fixtures.

If we later add lightweight frontend component tests, they should sit on top of this matrix rather than replace it.
