# Dogfood transcript corpus (anonymized)

This corpus supports deterministic parser and analysis regressions for real-session shapes without storing sensitive production data.

## Location

- Fixtures: `driftshield/tests/fixtures/transcripts/dogfood/*.jsonl`
- Golden expectations: `driftshield/tests/fixtures/transcripts/golden/dogfood_corpus_expectations.json`
- Regression tests:
  - `driftshield/tests/parsers/test_dogfood_golden.py`
  - `driftshield/tests/core/analysis/test_dogfood_golden.py`

## Redaction rules

Before adding or updating a fixture:

1. Replace all personal names with neutral placeholders (`User A`, `Agent`, etc.).
2. Remove emails, usernames, hostnames, paths, tokens, and IDs that map to real systems.
3. Remove organisation-specific project names unless already public.
4. Keep only fields needed for parser/analysis behaviour.
5. If uncertain whether a value is sensitive, remove it.

## Fixture maintenance rules

1. Keep one fixture per scenario type.
2. Keep fixtures small and stable (minimal lines needed for behaviour under test).
3. Update `dogfood_corpus_expectations.json` in the same change as fixture edits.
4. Run parser and analysis golden tests before merge.
5. For deliberate mismatch validation, temporarily change one expected value, verify the relevant test fails, then restore.

## Scenario coverage in this corpus

- clean
- assumption mutation (labelled for future heuristic implementation)
- policy divergence (labelled for future heuristic implementation)
- constraint violation (labelled for future heuristic implementation)
- multi-flag shape (currently deterministic `coverage_gap` detection in existing stack)
