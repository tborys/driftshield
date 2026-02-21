# UI PRD: DriftShield Investigation Interface (Post‑V1)

**Status:** Draft v1  
**Owners:** Demo + Devin (product decisions), Contributor (implementation planning)  
**Context:** Backend foundations are in place through v0.21.0; UI now needs to expose this capability simply.

---

## 1) Product Philosophy

This UI follows four non-negotiables:

1. **Simplicity is the ultimate sophistication**
   - If users need a manual, design failed.
   - Remove unnecessary controls and reduce cognitive load.

2. **User experience first, technology second**
   - Start from user jobs and outcomes, then map to backend.
   - Design is how it works, not only how it looks.

3. **Detail quality matters end-to-end**
   - Every interaction should feel deliberate and polished.
   - Hidden flows (loading, errors, empty states) must be as good as happy path.

4. **Integrated experience over fragmented tooling**
   - UI should present one coherent workflow across ingestion, analysis, validation and reporting.
   - Avoid exposing raw backend complexity to end users.

---

## 2) Problem Statement

DriftShield backend now supports signature foundations, recurrence, validation persistence, Graveyard collection and reporting.

But these capabilities are mostly CLI/backend-facing. Product adoption requires a clean UI that allows analysts to:
- inspect sessions and inflection points,
- validate system judgements,
- review recurrence and confidence,
- generate and consume evidence reports,
without switching tools or reading technical internals.

---

## 3) Objective

Build a minimal, clear investigation UI that makes DriftShield usable by non-engineering-heavy analysts while preserving depth for technical users.

---

## 4) Primary User Jobs

1. **Investigate a failed session quickly**
2. **Understand why the model flagged specific risks**
3. **Mark validations (accept/reject/needs review) with notes**
4. **See recurrence context and confidence**
5. **Generate concise evidence summaries for decision-makers**

---

## 5) UX Principles (Concrete)

- One primary action per screen.
- Prefer progressive disclosure over crowded panels.
- Show confidence and uncertainty explicitly.
- Keep language plain: avoid internal jargon when possible.
- Every screen must answer: “what do I do next?”

---

## 6) MVP UI Scope

### A) Session List + Filters
- List sessions with status, risk count, recurrence probability
- Filters: date range, flagged-only, risk class, source

### B) Session Investigation View
- Timeline/lineage view with inflection highlight
- Risk transitions and event-level evidence
- Clear “why flagged” section

### C) Validation Panel (critical)
- For inflection/risk/signature:
  - verdict: accept / reject / needs_review
  - confidence
  - notes
- Persist via existing backend validation APIs/services

### D) Recurrence Summary
- Show signature recurrence state (new/recurring/systemic)
- Show occurrence count and confidence/probability

### E) Report Surface
- Render generated markdown/json summaries
- Export/download action

---

## 7) Out of Scope (for first UI PRs)

- Full redesign system/theming overhaul
- Real-time collaboration
- Complex workflow automation
- Multi-tenant admin console
- Dedicated UI authentication flow (deferred to Operational Readiness phase)

---

## 8) Information Architecture

1. **Home / Sessions**
2. **Session Detail**
   - Overview
   - Lineage + inflection
   - Risk transitions
   - Recurrence
   - Validation
3. **Reports**
4. **Settings (later)**

---

## 9) Functional Requirements

- FR-UI-1: Display parsed session/event data from existing backend
- FR-UI-2: Display recurrence outputs (hash summary, class, probability)
- FR-UI-3: Capture and persist analyst validations (notes/verdict/confidence)
- FR-UI-4: Show Graveyard report summaries in readable format
- FR-UI-5: Handle empty/error/loading states cleanly

---

## 10) Non-Functional Requirements

- Fast initial render for common session sizes
- Keyboard-friendly basic navigation
- Accessible colour contrast and focus states
- Deterministic behaviour under partial backend failures

---

## 11) Success Metrics

- Time-to-first-useful-insight per session
- Validation completion rate
- % sessions reviewed without CLI fallback
- Analyst-reported usability (qualitative)

---

## 12) Proposed Delivery Plan (UI)

### UI-P1: Validation-first UI wiring (embedded)
- Add validation controls directly inside the existing investigation/session detail page
- Use a right-side Review drawer for focused interaction (not a separate page)
- Save to backend persistence
- Show confirmation + history timeline

### UI-P2: Recurrence and confidence UX
- Clear recurrence cards and explanation copy
- Integrate recurrence in overview and detail

### UI-P3: Report consumption UX
- Simple report browser and export/download affordance
- Graveyard summary render page

### UI-P4: Product polish and interaction refinement
- Empty/error/loading design polish
- Interaction tuning and visual consistency pass

---

## 13) Dependencies

- Existing backend capabilities from v0.15.0–v0.21.0
- PR #9 (P3.2 evaluation harness) for quality baseline visibility

---

## 14) Decisions and Remaining Questions

### Decided
1. Validation UI is embedded in investigation view using a right-side Review drawer.
2. MVP persona focus is mixed technical/non-technical users.
3. UI auth will be added later; validation actions in MVP proceed without dedicated UI auth flow.

### Follow-up note
- Defer UI authentication to a later phase (Operational Readiness track) and keep this explicitly out of UI-P1 scope.
