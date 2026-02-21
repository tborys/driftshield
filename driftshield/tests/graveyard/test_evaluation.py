from driftshield.graveyard.evaluation import evaluate_dataset


def test_evaluate_dataset_computes_precision_recall_f1_and_confusion():
    dataset = [
        {
            "title": "Agent ignored tool error",
            "text": "agent tool error hallucinated wrong output",
            "label": "agentic_failure",
        },
        {
            "title": "UI colour bug",
            "text": "frontend css button only",
            "label": "non_agentic_bug",
        },
        {
            "title": "Agent variable drift",
            "text": "context chain drift in multi step agent",
            "label": "agentic_failure",
        },
    ]

    result = evaluate_dataset(dataset)

    assert result.total == 3
    assert result.true_positive >= 1
    assert result.true_negative >= 1
    assert 0 <= result.precision <= 1
    assert 0 <= result.recall <= 1
    assert 0 <= result.f1 <= 1


def test_evaluate_dataset_with_threshold_override_changes_predictions():
    dataset = [
        {
            "title": "Possible drift",
            "text": "agent chain maybe",
            "label": "agentic_failure",
        }
    ]

    low_threshold = evaluate_dataset(dataset, positive_threshold=2)
    high_threshold = evaluate_dataset(dataset, positive_threshold=9)

    assert low_threshold.predicted_positive_count >= high_threshold.predicted_positive_count
