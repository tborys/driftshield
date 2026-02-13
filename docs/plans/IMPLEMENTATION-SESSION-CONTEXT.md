# DriftShield Implementation Session

## Session Purpose

Execute Phases 1-6 of the DriftShield v1 implementation plan. This session is for building code — the design session remains separate for coordination and review.

## Critical Rules

1. **TDD always** — Write the failing test first, run it, then implement
2. **Follow the plan exactly** — Tasks are in `docs/plans/2025-02-13-driftshield-v1-implementation.md`
3. **Commit after each task** — Small, atomic commits
4. **Add to existing files** — When the plan says "Modify", add to the file, don't replace it

## Before Starting

1. Read the implementation plan: `docs/plans/2025-02-13-driftshield-v1-implementation.md`
2. Read the design document for context: `docs/plans/2025-02-13-driftshield-v1-design.md`

## Execution Order

Execute tasks in this exact order:

### Phase 1: Project Foundation
- Task 1.1: Project Structure Setup

### Phase 2: Core Domain Models
- Task 2.1: EventType Enum
- Task 2.2: RiskClassification Model
- Task 2.3: CanonicalEvent Model (ADD to existing models.py)
- Task 2.4: Session Model (ADD to existing models.py)

### Phase 3: Lineage Graph
- Task 3.1: DecisionNode
- Task 3.2: LineageGraph Construction
- Task 3.3: Graph Path Traversal (ADD methods to LineageGraph)

### Phase 4: Graph Builder
- Task 4.1: Build Graph from Events

### Phase 5: Synthetic Validation Scenarios
- Task 5.1: Create Test Fixtures Module
- Task 5.2: Scenario Validation Tests

### Phase 6: Inflection Node Detection
- Task 6.1: Find Inflection Node

## Task Execution Pattern

For each task:

```
1. Read the task from the implementation plan
2. Create the test file / add the test
3. Run pytest to verify it FAILS
4. Create/modify the implementation file
5. Run pytest to verify it PASSES
6. Commit with the message from the plan
```

## Commands Reference

```bash
# Install dependencies (after Task 1.1)
cd driftshield
python -m pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/core/test_models.py::TestEventType -v

# Commit pattern
git add <files>
git commit -m "<message from plan>"
```

## Success Criteria

Phase 1-6 complete when:
- All tests pass: `pytest tests/ -v` shows green
- 12 commits made (one per task)
- Inflection detection works against all 3 synthetic scenarios

## If You Get Stuck

- Re-read the specific task in the implementation plan
- Check imports — the plan specifies exact import paths
- For "add to existing file" tasks, read the file first

---

**Start with Task 1.1: Project Structure Setup**
