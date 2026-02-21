from driftshield.core.signatures.models import SignatureRiskClass
from driftshield.core.signatures.templates import SignatureTemplateLibrary


def test_template_library_contains_ten_templates() -> None:
    templates = SignatureTemplateLibrary().all()
    assert len(templates) == 10


def test_template_lookup_returns_expected_signature() -> None:
    template = SignatureTemplateLibrary().get("SIG-TCV-001")
    assert template is not None
    assert template.risk_class == SignatureRiskClass.TOOL_CONTRACT_VIOLATION
    assert template.title == "Tool Contract Violation Ignored"
