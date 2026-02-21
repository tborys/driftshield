from driftshield.core.signatures.quality import QualityGateEvaluator, QualityGateInput


def test_quality_gate_accept_when_all_scores_good() -> None:
    evaluator = QualityGateEvaluator()
    result = evaluator.evaluate(
        QualityGateInput(
            evidence_completeness=0.88,
            ambiguity=0.1,
            duplicate_similarity=0.22,
            reviewer_verdict="accept",
        )
    )
    assert result.passed is True
    assert result.bucket == "auto_accept"


def test_quality_gate_routes_to_review_when_borderline() -> None:
    evaluator = QualityGateEvaluator()
    result = evaluator.evaluate(
        QualityGateInput(
            evidence_completeness=0.72,
            ambiguity=0.31,
            duplicate_similarity=0.40,
            reviewer_verdict="needs_review",
        )
    )
    assert result.passed is False
    assert result.bucket == "needs_review"
    assert "reviewer_verdict" in result.reasons
