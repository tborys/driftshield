from collections import Counter

from driftshield.core.signatures.models import SignatureRiskClass
from driftshield.core.signatures.templates import SignatureTemplateLibrary


def test_template_library_contains_twenty_templates() -> None:
    templates = SignatureTemplateLibrary().all()
    assert len(templates) == 20


def test_each_risk_class_has_two_seed_templates() -> None:
    templates = SignatureTemplateLibrary().all()
    counts = Counter(t.risk_class for t in templates)

    assert set(counts.keys()) == set(SignatureRiskClass)
    assert all(count == 2 for count in counts.values())


def test_template_lookup_returns_expected_signature() -> None:
    template = SignatureTemplateLibrary().get("SIG-TCV-001")
    assert template is not None
    assert template.risk_class == SignatureRiskClass.TOOL_CONTRACT_VIOLATION
    assert template.title == "Tool Contract Violation Ignored"


def test_templates_have_signature_specific_markers() -> None:
    templates = SignatureTemplateLibrary().all()
    assert all(template.invariant.lexical_markers for template in templates)
    assert len({tuple(t.invariant.lexical_markers) for t in templates}) == len(templates)
