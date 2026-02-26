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
    lexical_markers: list[str],
    temporal_constraints: list[str] | None = None,
    state_constraints: list[str] | None = None,
    model_score: float = 0.72,
) -> DetectionSignature:
    return DetectionSignature(
        signature_id=signature_id,
        title=title,
        risk_class=risk_class,
        status=SignatureStatus.CANDIDATE,
        invariant=SignatureInvariant(
            graph_pattern=graph_pattern,
            temporal_constraints=temporal_constraints or ["verify before write"],
            state_constraints=state_constraints or ["preserve entity consistency"],
            lexical_markers=lexical_markers,
            invariant_fingerprint=fingerprint,
        ),
        confidence=SignatureConfidence(model_score=model_score),
        provenance=[
            SignatureProvenance(
                source_type="template_seed",
                source_ref="post-v1-prd",
            )
        ],
        description=description,
    )


class SignatureTemplateLibrary:
    """Registry of twenty proprietary detection signature templates."""

    def __init__(self) -> None:
        self._templates = {
            "SIG-VD-001": _template(
                "SIG-VD-001",
                "Variable Drift Propagation",
                SignatureRiskClass.VARIABLE_DRIFT,
                "retrieve->transform->write",
                "fp-vd-001",
                "Variable aliasing changes silently propagate downstream.",
                lexical_markers=["alias", "mapped field", "normalised value"],
            ),
            "SIG-VD-002": _template(
                "SIG-VD-002",
                "Metric Substitution Drift",
                SignatureRiskClass.VARIABLE_DRIFT,
                "retrieve_metric->transform_metric->write_metric",
                "fp-vd-002",
                "Metric substitution silently swaps semantic meaning (e.g. revenue vs profit).",
                lexical_markers=["substitute metric", "same column", "approximate mapping"],
            ),
            "SIG-CC-001": _template(
                "SIG-CC-001",
                "Context Contamination via Irrelevant Injection",
                SignatureRiskClass.CONTEXT_CONTAMINATION,
                "retrieve_irrelevant->reason->write",
                "fp-cc-001",
                "Irrelevant retrieved context influences decision path.",
                lexical_markers=["irrelevant context", "unrelated document", "carry over"],
            ),
            "SIG-CC-002": _template(
                "SIG-CC-002",
                "Cross-Session Context Bleed",
                SignatureRiskClass.CONTEXT_CONTAMINATION,
                "reuse_previous_context->reason->write",
                "fp-cc-002",
                "State from a previous session contaminates current-session reasoning.",
                lexical_markers=["previous conversation", "last request", "earlier session"],
            ),
            "SIG-TCV-001": _template(
                "SIG-TCV-001",
                "Tool Contract Violation Ignored",
                SignatureRiskClass.TOOL_CONTRACT_VIOLATION,
                "tool_error->no_retry->write",
                "fp-tcv-001",
                "Tool schema/type mismatch ignored and propagated.",
                lexical_markers=["schema mismatch", "invalid type", "ignored tool error"],
            ),
            "SIG-TCV-002": _template(
                "SIG-TCV-002",
                "Silent Tool Response Coercion",
                SignatureRiskClass.TOOL_CONTRACT_VIOLATION,
                "tool_partial_response->coerce->write",
                "fp-tcv-002",
                "Malformed tool response is coerced without explicit validation.",
                lexical_markers=["coerce response", "best effort parse", "fallback parser"],
            ),
            "SIG-CG-001": _template(
                "SIG-CG-001",
                "Coverage Gap at Branch Condition",
                SignatureRiskClass.COVERAGE_GAP,
                "missing_evidence->branch->write",
                "fp-cg-001",
                "Branch executes without mandatory evidence coverage.",
                lexical_markers=["missing evidence", "assume true", "continue anyway"],
            ),
            "SIG-CG-002": _template(
                "SIG-CG-002",
                "Unscanned Source Coverage Gap",
                SignatureRiskClass.COVERAGE_GAP,
                "partial_scan->decide->write",
                "fp-cg-002",
                "Decision is made before required sources are scanned.",
                lexical_markers=["partial scan", "remaining sources", "timebox exceeded"],
            ),
            "SIG-PD-001": _template(
                "SIG-PD-001",
                "Policy Divergence under Fallback",
                SignatureRiskClass.POLICY_DIVERGENCE,
                "fallback->skip_policy->write",
                "fp-pd-001",
                "Fallback path bypasses required policy checks.",
                lexical_markers=["skip policy", "fallback mode", "temporary exception"],
            ),
            "SIG-PD-002": _template(
                "SIG-PD-002",
                "Policy Scope Misapplication",
                SignatureRiskClass.POLICY_DIVERGENCE,
                "select_wrong_policy->approve",
                "fp-pd-002",
                "Incorrect policy scope applied to the current workflow context.",
                lexical_markers=["wrong policy", "scope mismatch", "applies to another region"],
            ),
            "SIG-UV-001": _template(
                "SIG-UV-001",
                "Unverified Write-to-System-of-Record",
                SignatureRiskClass.UNVERIFIED_WRITE,
                "infer->no_verify->write_system",
                "fp-uv-001",
                "System-of-record write occurs without verification node.",
                lexical_markers=["write without verify", "direct update", "skip confirmation"],
                temporal_constraints=["explicit verify before system write"],
            ),
            "SIG-UV-002": _template(
                "SIG-UV-002",
                "External Commit Without Two-Phase Confirmation",
                SignatureRiskClass.UNVERIFIED_WRITE,
                "plan_write->commit_external",
                "fp-uv-002",
                "External side-effect is committed without two-phase confirmation.",
                lexical_markers=["commit now", "finalise immediately", "no second check"],
                temporal_constraints=["require two-step confirmation before commit"],
            ),
            "SIG-AM-001": _template(
                "SIG-AM-001",
                "Assumption Mutation Cascade",
                SignatureRiskClass.ASSUMPTION_MUTATION,
                "assumption->promote_fact->write",
                "fp-am-001",
                "Speculative assumption promoted to fact across steps.",
                lexical_markers=["assume", "probably", "treat as confirmed"],
            ),
            "SIG-AM-002": _template(
                "SIG-AM-002",
                "Confidence Inflation Drift",
                SignatureRiskClass.ASSUMPTION_MUTATION,
                "low_confidence->relabel_high_confidence->approve",
                "fp-am-002",
                "Low-confidence inference is re-labelled as high-confidence without evidence.",
                lexical_markers=["high confidence", "certain enough", "confidence upgraded"],
            ),
            "SIG-TMS-001": _template(
                "SIG-TMS-001",
                "Tool Mis-sequencing",
                SignatureRiskClass.TOOL_MISSEQUENCING,
                "write->reconcile",
                "fp-tms-001",
                "Execution order violates dependency sequence.",
                lexical_markers=["write first", "reconcile later", "post-hoc validation"],
                temporal_constraints=["dependency checks before write"],
            ),
            "SIG-TMS-002": _template(
                "SIG-TMS-002",
                "Parallel Branch Race Commit",
                SignatureRiskClass.TOOL_MISSEQUENCING,
                "parallel_tools->race->commit",
                "fp-tms-002",
                "Parallel branch outputs race and commit before synchronisation gate.",
                lexical_markers=["race", "parallel branch", "first result wins"],
                temporal_constraints=["synchronise branches before commit"],
            ),
            "SIG-HD-001": _template(
                "SIG-HD-001",
                "Hallucination via Distraction",
                SignatureRiskClass.HALLUCINATION_DISTRACTION,
                "noise_context->unsupported_entity->write",
                "fp-hd-001",
                "Distractor context introduces unsupported entity claims.",
                lexical_markers=["unverified entity", "looks plausible", "not in sources"],
            ),
            "SIG-HD-002": _template(
                "SIG-HD-002",
                "Fabricated Citation Anchoring",
                SignatureRiskClass.HALLUCINATION_DISTRACTION,
                "fabricated_citation->justify->write",
                "fp-hd-002",
                "Fabricated citation is used to anchor downstream decisions.",
                lexical_markers=["fabricated source", "citation missing", "cannot retrieve reference"],
            ),
            "SIG-CR-001": _template(
                "SIG-CR-001",
                "Constraint Relaxation Drift",
                SignatureRiskClass.CONSTRAINT_RELAXATION,
                "retry->relax_constraint->approve",
                "fp-cr-001",
                "Constraint thresholds loosen across retries without approval.",
                lexical_markers=["relax threshold", "temporary override", "accept lower bar"],
            ),
            "SIG-CR-002": _template(
                "SIG-CR-002",
                "Guardrail Timeout Bypass",
                SignatureRiskClass.CONSTRAINT_RELAXATION,
                "guardrail_timeout->disable_guardrail->approve",
                "fp-cr-002",
                "Guardrail timeout causes control to be disabled rather than retried safely.",
                lexical_markers=["timeout bypass", "disable guardrail", "force approve"],
            ),
        }

    def all(self) -> list[DetectionSignature]:
        return list(self._templates.values())

    def get(self, signature_id: str) -> DetectionSignature | None:
        return self._templates.get(signature_id)
