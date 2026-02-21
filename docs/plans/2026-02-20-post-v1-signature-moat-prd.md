# Post‑V1 PRD: Signature Moat Programme

**Status:** Draft v1  
**Owners:** Contributor (coordination), Demo + Devin (final decisions)  
**Epic:** https://github.com/demouser/driftshield-agentic/issues/1  
**Planning source of truth:** `docs/plans/beyond-v1-ideas.md`

---

## 1) Problem Statement
Current tooling can show that an agent failed, but not reliably isolate where reasoning diverged and whether the same failure will recur. To build a defensible moat, DriftShield must move from public risk labels to proprietary, reproducible detection signatures with provenance and recurrence learning.

## 2) Objective
Build a post‑V1 system that:
1. Defines robust signature primitives (schema + templates + quality gates)
2. Learns recurrence patterns across sessions
3. Ingests real-world failure evidence (GitHub Graveyard + internal fixtures)
4. Produces auditable outputs for product, sales, and investor proof

## 3) Success Criteria
- Signature schema adopted as canonical internal standard
- First 10 validated signature templates live
- Recurrence detection functioning on historical sessions
- Validation decisions persisted and exportable for model improvement
- GitHub Graveyard spike completed with signal quality benchmark
- First “State of OSS Agent Failures” report draft generated

## 4) Scope & Priorities

### P0 — Signature Foundation
1. Signature schema + ontology hardening
2. First 10 signature templates
3. Quality gate spec (evidence completeness, ambiguity, de-dup, reviewer verdict model)

### P1 — Feedback Loop / Learning Core
4. Cross-session recurrence detection
5. Persist analyst validation decisions
6. Export validated training data for model fine-tuning loop

### P2 — Data Acquisition & Proof
7. OSS ingestion + extraction pipeline (**GitHub Graveyard**)
8. “State of OSS Agent Failures” reporting workflow
9. Demo scenario transcript fixtures + richer seed data

### P3 — Scale & Hardening
10. Parser ecosystem expansion
11. Operational readiness (auth, RBAC, audit logs, multi-tenant)
12. Scale/integration/drift alerting + UI auth hardening

## 5) Functional Requirements

### FR-1 Signature System
- Create versioned `signature_id` with invariant fingerprint
- Capture provenance (source URL, parser version, evidence span)
- Store public class + proprietary invariants/features/confidence

### FR-2 Quality & Review
- Score evidence completeness and ambiguity
- De-dup clustering with similarity threshold
- Human verdict: accept/reject/needs_review

### FR-3 Recurrence Engine
- Match signatures across sessions via hash + topology features
- Expose recurrence frequency and trend

### FR-4 Validation Persistence
- Persist analyst validations (inflection, risk flag, signature)
- Support export to downstream training pipelines

### FR-5 GitHub Graveyard
- Collect issues/comments from selected OSS repos
- Extract candidate failure traces
- Map to canonical signature candidates with provenance

### FR-6 Reporting
- Generate periodic summary of failure modes, recurrence, and trends
- Produce investor/customer-safe aggregate outputs

## 6) Engineering Quality Gates (Mandatory)

### TDD is mandatory
For every important step/phase:
1. Write failing tests first (unit/integration as applicable)
2. Implement minimal code to pass tests
3. Refactor while keeping tests green
4. Commit only after tests are passing

### Test validation is mandatory
- Always run relevant test suites before marking a task complete
- For cross-cutting changes, run full test suite
- No “done” status without explicit test pass confirmation
- Any failing test blocks merge until resolved or explicitly waived by Demo

## 7) Client Data Collection & Learning Policy

### Default data posture
- Client data is tenant-isolated and private by default
- No raw cross-tenant sharing
- No client traces used for shared model learning unless explicitly enabled

### Collection modes
- **Private mode (default):** signatures and validations stay within client tenant scope
- **Shared learning mode (opt-in):** anonymised/aggregated signature artefacts can be used to improve global detection quality

### Data controls
- Capture provenance for all client-derived signatures (tenant, source, timestamp, parser version)
- Apply anonymisation/redaction before any shared-learning export
- Enforce retention windows and deletion workflows per contract
- Maintain audit logs for access and export actions

### Contract and compliance requirements
- Explicit consent language for shared learning in commercial terms/DPA
- Right-to-delete support for client-contributed data
- Ability to produce audit trail of what data contributed to each learned signature

## 8) Non-Goals (this phase)
- Full multi-tenant enterprise rollout
- Real-time production alerting at scale
- Broad parser support before signature core is stable

## 9) Dependencies
- Phase 14 complete
- Existing DB tables from Phase 10 available
- `beyond-v1-ideas.md` remains planning source of truth
- GitHub issue #1 remains parent epic for execution breakdown

## 10) Risks & Mitigations
- **Noisy OSS data** → spike first, strict quality gates before scale
- **Weak invariants** → lock schema early, require reviewer validation
- **Premature infra expansion** → defer P3 until P0/P1/P2 evidence is solid

## 11) Delivery Flow
- **Gate A:** update/approve doc-level priorities
- **Gate B:** convert to ranked execution backlog with acceptance criteria
- **Gate C:** create child issues and assign owners

## 12) Open Decisions
1. Keep recurrence in same epic as signature work, or sibling epic?
2. GitHub Graveyard scale timing after spike (immediate vs after first recurrence milestone)?
3. Initial OSS repos for spike

## 13) Immediate Next Actions
1. Approve this PRD
2. Link this doc from issue #1
3. Create child issues mapped to P0/P1/P2/P3 with blockers and milestones
