from __future__ import annotations

from dataclasses import dataclass

from driftshield.graveyard.classifier import classify_thread


@dataclass(slots=True)
class EvaluationResult:
    total: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    predicted_positive_count: int


def evaluate_dataset(
    dataset: list[dict],
    *,
    positive_threshold: int = 4,
) -> EvaluationResult:
    tp = fp = tn = fn = 0

    for row in dataset:
        title = row.get("title", "")
        text = row.get("text", "")
        label = row.get("label", "non_agentic_bug")

        classification = classify_thread(title, text)
        predicted_positive = classification.score >= positive_threshold
        actual_positive = label == "agentic_failure"

        if predicted_positive and actual_positive:
            tp += 1
        elif predicted_positive and not actual_positive:
            fp += 1
        elif not predicted_positive and not actual_positive:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return EvaluationResult(
        total=len(dataset),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        predicted_positive_count=tp + fp,
    )
