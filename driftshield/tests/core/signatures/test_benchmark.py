from pathlib import Path

from driftshield.core.signatures.benchmark import (
    BenchmarkExample,
    evaluate_signature_library,
    load_benchmark_dataset,
)
from driftshield.core.signatures.models import SignatureRiskClass


def test_load_benchmark_dataset() -> None:
    dataset_path = Path(__file__).resolve().parents[3] / "data" / "signature-benchmark.jsonl"
    rows = load_benchmark_dataset(dataset_path)

    assert len(rows) == 20
    assert rows[0].expected_risk_class == SignatureRiskClass.VARIABLE_DRIFT


def test_evaluate_signature_library_on_seed_dataset() -> None:
    dataset_path = Path(__file__).resolve().parents[3] / "data" / "signature-benchmark.jsonl"
    rows = load_benchmark_dataset(dataset_path)
    result = evaluate_signature_library(rows)

    assert result.dataset_size == 20
    assert result.exact_match_rate == 1.0

    for risk_class in SignatureRiskClass:
        family = result.per_family[risk_class]
        assert family.support == 2
        assert family.precision == 1.0
        assert family.recall == 1.0
        assert family.f1 == 1.0


def test_evaluate_signature_library_handles_no_match_case() -> None:
    rows = [
        BenchmarkExample(
            fixture_id="no-match",
            graph_pattern="unknown->path",
            lexical_markers=["none"],
            expected_risk_class=SignatureRiskClass.COVERAGE_GAP,
        )
    ]

    result = evaluate_signature_library(rows)

    assert result.exact_match_rate == 0.0
    assert result.per_family[SignatureRiskClass.COVERAGE_GAP].recall == 0.0
