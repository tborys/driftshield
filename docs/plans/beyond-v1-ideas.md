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

## Demo Scenarios and Seed Data

V1 ships with a single clean session fixture. To properly demonstrate DriftShield's value, the Docker deployment needs richer seed data covering failure modes the analysis engine already detects.

### Transcript fixtures to create

Each scenario needs a `.jsonl` transcript file that triggers detection when ingested via the parser pipeline. The existing Python test scenarios (in `tests/fixtures/scenarios.py`) demonstrate the patterns but use in-memory objects rather than transcript files.

**Coverage gap** (coverage_gap, assumption_mutation flags + inflection)
Agent reviews a complex document and misses a material exception. Contract review agent processes an indemnification clause with 4 subsections, but subsection (c) containing an "except where" carve-out is omitted from the summary. Agent concludes "no material risks" despite the gap.

**Assumption introduction** (assumption_mutation flag + inflection)
Agent makes an inference not supported by the data. Underwriting agent sees a 6pt margin decline for a client but a 4pt sector average decline. Instead of computing relative underperformance (2pt worse than peers), agent concludes "industry wide trend explains client decline" and recommends approval.

**Cross tool contamination** (context_contamination flag + inflection)
Output from one tool context incorrectly leaks into another. Order processing agent fetches customer data with a "gold" discount tier for product category A, then applies that discount to a product in category B where it doesn't apply. Results in incorrect pricing.

**Policy divergence** (policy_divergence flag + inflection)
Agent has explicit instructions or constraints but takes an action that contradicts them. For example, a compliance agent with a rule to escalate any transaction above a threshold processes one that exceeds the limit without escalating.

**Constraint violation** (constraint_violation flag + inflection)
Agent violates a hard boundary or system constraint. For example, a scheduling agent books a resource beyond its maximum capacity, or an approval agent authorises a request outside its delegation limits.

**Multi flag session** (multiple flags + inflection)
A longer session that accumulates multiple risk flags across several decision points. Demonstrates how risk compounds through a chain of reasoning. Useful for testing the lineage graph with a more complex topology.

**Clean session variants**
Additional clean transcripts showing healthy agent behaviour across different domains (code review, data analysis, document processing). Useful for contrast and for verifying the UI handles sessions with no flags gracefully.

### Implementation approach

- Write a transcript generator that converts the existing Python scenario objects into `.jsonl` format compatible with the Claude Code parser (or a new generic parser)
- Alternatively, create a new "scenario" parser format that maps directly to `CanonicalEvent` fields
- Place generated fixtures in `docker/fixtures/` so the seed script picks them up automatically
- Optionally gate seeding behind an env var (`SEED_DATA=true`) for users who want a clean start

## UI Authentication

V1 embeds the API key in the frontend JS bundle at build time via `VITE_API_KEY`. This works but means the key is visible in client source. Better approaches for post v1:

- Cookie based session auth for the UI (API key remains for external integrations)
- Skip auth for same origin requests from the co-located frontend
- Separate UI auth flow with login page

## Scale and Integration

- Horizontal scaling (separate worker processes for analysis)
- Message queue for async ingestion
- S3 / object storage for large transcripts
- API rate limiting and request throttling
