# Beyond V1: Ideas and Directions

**Status:** Not planned. Ideas to evaluate after Phase 14 completes.

---

## Recurrence Detection and Training Data

The highest value follow on from v1. DB tables for recurrence signatures and session signatures exist from Phase 10. UI validation controls exist from Phase 13 but persist only in local state.

- Build recurrence detection logic (cross session pattern matching using signature hashes)
- Persist analyst validation decisions to training data tables (inflection validations, risk flag validations, signature validations)
- Export validated data for model fine tuning
- Close the feedback loop between analyst judgement and system accuracy

## Parser Ecosystem

Currently only a Claude Code parser exists. Expanding parser coverage increases the addressable use case.

- OpenAI / ChatGPT parser
- LangChain agent parser
- Custom agent format parser
- Parser plugin system for third party contributions

## Operational Readiness

Move from single user self hosted to multi user production ready.

- JWT or OAuth authentication (replacing shared API key)
- Role based access (analyst vs admin)
- Audit logging for compliance
- Multi tenant support

## Drift Alerting

The long term vision: detect reasoning drift before material impact.

- Real time webhook ingestion for live monitoring
- Threshold based drift alerts
- Grafana / metrics integration
- Telemetry export pipeline

## Scale and Integration

- Horizontal scaling (separate worker processes for analysis)
- Message queue for async ingestion
- S3 / object storage for large transcripts
- API rate limiting and request throttling
