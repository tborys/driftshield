"""Benchmark utilities for signature-library quality tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from driftshield.core.signatures.models import SignatureRiskClass
from driftshield.core.signatures.templates import SignatureTemplateLibrary


@dataclass(slots=True)
class BenchmarkExample:
    fixture_id: str
    graph_pattern: str
    lexical_markers: list[str]
    expected_risk_class: SignatureRiskClass


@dataclass(slots=True)
class FamilyMetrics:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    support: int


@dataclass(slots=True)
class SignatureBenchmarkResult:
    dataset_size: int
    exact_match_rate: float
    average_candidate_signatures: float
    per_family: dict[SignatureRiskClass, FamilyMetrics]

    def to_dict(self) -> dict:
        return {
            "dataset_size": self.dataset_size,
            "exact_match_rate": self.exact_match_rate,
            "average_candidate_signatures": self.average_candidate_signatures,
            "per_family": {
                risk_class.value: {
                    "precision": metrics.precision,
                    "recall": metrics.recall,
                    "f1": metrics.f1,
                    "true_positive": metrics.true_positive,
                    "false_positive": metrics.false_positive,
                    "false_negative": metrics.false_negative,
                    "support": metrics.support,
                }
                for risk_class, metrics in self.per_family.items()
            },
        }


@dataclass(slots=True)
class _Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0


def load_benchmark_dataset(path: Path) -> list[BenchmarkExample]:
    rows: list[BenchmarkExample] = []

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            rows.append(
                BenchmarkExample(
                    fixture_id=payload["fixture_id"],
                    graph_pattern=payload["graph_pattern"],
                    lexical_markers=list(payload.get("lexical_markers", [])),
                    expected_risk_class=SignatureRiskClass(payload["expected_risk_class"]),
                )
            )

    return rows


def evaluate_signature_library(
    rows: list[BenchmarkExample],
    *,
    library: SignatureTemplateLibrary | None = None,
) -> SignatureBenchmarkResult:
    templates = (library or SignatureTemplateLibrary()).all()
    counters = {risk_class: _Counts() for risk_class in SignatureRiskClass}

    exact_matches = 0
    total_candidates = 0

    for row in rows:
        predicted_signatures = [
            template
            for template in templates
            if template.invariant.graph_pattern == row.graph_pattern
            and _has_marker_overlap(template.invariant.lexical_markers, row.lexical_markers)
        ]

        predicted_risk_classes = {template.risk_class for template in predicted_signatures}
        total_candidates += len(predicted_signatures)

        if row.expected_risk_class in predicted_risk_classes:
            exact_matches += 1

        for risk_class in SignatureRiskClass:
            actual = row.expected_risk_class == risk_class
            predicted = risk_class in predicted_risk_classes
            counts = counters[risk_class]

            if predicted and actual:
                counts.tp += 1
            elif predicted and not actual:
                counts.fp += 1
            elif (not predicted) and actual:
                counts.fn += 1

    per_family: dict[SignatureRiskClass, FamilyMetrics] = {}
    for risk_class, counts in counters.items():
        precision = counts.tp / (counts.tp + counts.fp) if (counts.tp + counts.fp) else 0.0
        recall = counts.tp / (counts.tp + counts.fn) if (counts.tp + counts.fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        support = sum(1 for row in rows if row.expected_risk_class == risk_class)

        per_family[risk_class] = FamilyMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            true_positive=counts.tp,
            false_positive=counts.fp,
            false_negative=counts.fn,
            support=support,
        )

    return SignatureBenchmarkResult(
        dataset_size=len(rows),
        exact_match_rate=(exact_matches / len(rows) if rows else 0.0),
        average_candidate_signatures=(total_candidates / len(rows) if rows else 0.0),
        per_family=per_family,
    )


def _has_marker_overlap(template_markers: list[str], observed_markers: list[str]) -> bool:
    if not template_markers:
        return True
    observed = {marker.lower().strip() for marker in observed_markers}
    return any(marker.lower() in observed for marker in template_markers)
