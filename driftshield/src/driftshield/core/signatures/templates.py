"""Built-in template library for initial signature coverage."""

from driftshield.core.signatures.models import (
    DetectionSignature,
    SignatureConfidence,
    SignatureInvariant,
    SignatureProvenance,
    SignatureRiskClass,
    SignatureStatus,
)


def _template(
    signature_id: str,
    title: str,
    risk_class: SignatureRiskClass,
    graph_pattern: str,
    fingerprint: str,
    description: str,
) -> DetectionSignature:
    return DetectionSignature(
        signature_id=signature_id,
        title=title,
        risk_class=risk_class,
        status=SignatureStatus.CANDIDATE,
        invariant=SignatureInvariant(
            graph_pattern=graph_pattern,
            temporal_constraints=["verify before write"],
            state_constraints=["preserve entity consistency"],
            lexical_markers=["fallback", "using previous value"],
            invariant_fingerprint=fingerprint,
        ),
        confidence=SignatureConfidence(model_score=0.7),
        provenance=[
            SignatureProvenance(
                source_type="template_seed",
                source_ref="post-v1-prd",
            )
        ],
        description=description,
    )


class SignatureTemplateLibrary:
    """Registry of the first ten proprietary detection signature templates."""

    def __init__(self) -> None:
        self._templates = {
            "SIG-VD-001": _template(
                "SIG-VD-001",
                "Variable Drift Propagation",
                SignatureRiskClass.VARIABLE_DRIFT,
                "retrieve->transform->write",
                "fp-vd-001",
                "Variable aliasing changes silently propagate downstream.",
            ),
            "SIG-CC-001": _template(
                "SIG-CC-001",
                "Context Contamination via Irrelevant Injection",
                SignatureRiskClass.CONTEXT_CONTAMINATION,
                "retrieve_irrelevant->reason->write",
                "fp-cc-001",
                "Irrelevant retrieved context influences decision path.",
            ),
            "SIG-TCV-001": _template(
                "SIG-TCV-001",
                "Tool Contract Violation Ignored",
                SignatureRiskClass.TOOL_CONTRACT_VIOLATION,
                "tool_error->no_retry->write",
                "fp-tcv-001",
                "Tool schema/type mismatch ignored and propagated.",
            ),
            "SIG-CG-001": _template(
                "SIG-CG-001",
                "Coverage Gap at Branch Condition",
                SignatureRiskClass.COVERAGE_GAP,
                "missing_evidence->branch->write",
                "fp-cg-001",
                "Branch executes without mandatory evidence coverage.",
            ),
            "SIG-PD-001": _template(
                "SIG-PD-001",
                "Policy Divergence under Fallback",
                SignatureRiskClass.POLICY_DIVERGENCE,
                "fallback->skip_policy->write",
                "fp-pd-001",
                "Fallback path bypasses required policy checks.",
            ),
            "SIG-UV-001": _template(
                "SIG-UV-001",
                "Unverified Write-to-System-of-Record",
                SignatureRiskClass.UNVERIFIED_WRITE,
                "infer->no_verify->write_system",
                "fp-uv-001",
                "System-of-record write occurs without verification node.",
            ),
            "SIG-AM-001": _template(
                "SIG-AM-001",
                "Assumption Mutation Cascade",
                SignatureRiskClass.ASSUMPTION_MUTATION,
                "assumption->promote_fact->write",
                "fp-am-001",
                "Speculative assumption promoted to fact across steps.",
            ),
            "SIG-TMS-001": _template(
                "SIG-TMS-001",
                "Tool Mis-sequencing",
                SignatureRiskClass.TOOL_MISSEQUENCING,
                "write->reconcile",
                "fp-tms-001",
                "Execution order violates dependency sequence.",
            ),
            "SIG-HD-001": _template(
                "SIG-HD-001",
                "Hallucination via Distraction",
                SignatureRiskClass.HALLUCINATION_DISTRACTION,
                "noise_context->unsupported_entity->write",
                "fp-hd-001",
                "Distractor context introduces unsupported entity claims.",
            ),
            "SIG-CR-001": _template(
                "SIG-CR-001",
                "Constraint Relaxation Drift",
                SignatureRiskClass.CONSTRAINT_RELAXATION,
                "retry->relax_constraint->approve",
                "fp-cr-001",
                "Constraint thresholds loosen across retries without approval.",
            ),
        }

    def all(self) -> list[DetectionSignature]:
        return list(self._templates.values())

    def get(self, signature_id: str) -> DetectionSignature | None:
        return self._templates.get(signature_id)
