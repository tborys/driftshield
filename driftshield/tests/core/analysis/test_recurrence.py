from driftshield.core.analysis.recurrence import RecurrenceEngine, RecurrenceLevel
from tests.fixtures.scenarios import coverage_gap_scenario


def _events():
    graph, _ = coverage_gap_scenario()
    return [node.event for node in graph.nodes]


def test_signature_hash_is_stable_for_identical_inputs() -> None:
    events = _events()
    engine = RecurrenceEngine()

    first = engine.signature_hash(events)
    second = engine.signature_hash(events)

    assert first == second


def test_evaluate_classifies_recurring_pattern() -> None:
    events = _events()
    engine = RecurrenceEngine()
    sig_hash = engine.signature_hash(events)

    assessment = engine.evaluate(events, historical_counts={sig_hash: 2})

    assert assessment.level == RecurrenceLevel.RECURRING
    assert assessment.occurrence_count == 3
    assert assessment.probability == "medium"


def test_evaluate_classifies_systemic_when_frequent() -> None:
    events = _events()
    engine = RecurrenceEngine()
    sig_hash = engine.signature_hash(events)

    assessment = engine.evaluate(events, historical_counts={sig_hash: 5})

    assert assessment.level == RecurrenceLevel.SYSTEMIC
    assert assessment.occurrence_count == 6
    assert assessment.probability == "high"
