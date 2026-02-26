"""Signature foundation primitives."""

from driftshield.core.signatures.benchmark import (
    BenchmarkExample,
    SignatureBenchmarkResult,
    evaluate_signature_library,
    load_benchmark_dataset,
)
from driftshield.core.signatures.models import (
    DetectionSignature,
    SignatureConfidence,
    SignatureInvariant,
    SignatureProvenance,
    SignatureRiskClass,
    SignatureStatus,
)
from driftshield.core.signatures.quality import (
    QualityGateEvaluator,
    QualityGateInput,
    QualityGateResult,
)
from driftshield.core.signatures.templates import SignatureTemplateLibrary

__all__ = [
    "BenchmarkExample",
    "SignatureBenchmarkResult",
    "evaluate_signature_library",
    "load_benchmark_dataset",
    "DetectionSignature",
    "SignatureConfidence",
    "SignatureInvariant",
    "SignatureProvenance",
    "SignatureRiskClass",
    "SignatureStatus",
    "QualityGateEvaluator",
    "QualityGateInput",
    "QualityGateResult",
    "SignatureTemplateLibrary",
]
