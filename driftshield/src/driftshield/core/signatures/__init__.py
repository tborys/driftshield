"""Signature foundation primitives."""

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
