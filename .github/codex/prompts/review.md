Review this DriftShield pull request without making code changes.

Start with `AGENTS.md` and `CLAUDE.md` for repo-specific conventions and review priorities.
Use `$driftshield-pr-review` from `.agents/skills/driftshield-pr-review` as the repo-specific review workflow.
Then read `.github/codex/context/pr-review-context.md`, inspect the actual diff against the base branch named there, and read the touched files in full before concluding.

Focus on:
1. Correctness and regressions: logic bugs, missing edge cases, broken imports, stale references, API or CLI breakage
2. OSS boundary and release safety: proprietary code leakage, sensitive docs or assets, accidental reintroduction of private features, references to private sibling repos or planning docs, hardcoded secrets
3. Backend and data integrity: schema drift, migration gaps, persistence mismatches, API/schema mismatches, backend/frontend parity
4. Frontend and browser behaviour: broken routes, dead navigation, missing loading or error states, dashboard usability regressions
5. Tests and verification: missing or stale tests, weak coverage for changed behaviour, lack of browser verification when UI changed
6. Documentation and workflow consistency: linked issue acceptance criteria not met, PR description gaps, instructions that no longer match the code

Output requirements:
- Findings first, grouped by severity: blocking, important, minor
- Include file paths when calling out a concrete problem
- If you find no issues, say so explicitly
- After findings, include short residual risks or verification gaps
- End with one sentence giving the overall assessment

Do not rubber stamp. Prioritise bugs, regressions, boundary leaks, and missing verification over style nits.
