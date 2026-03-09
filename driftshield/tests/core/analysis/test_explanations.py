from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from driftshield.core.analysis.risk import RiskAnalyzer, RiskHeuristic
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import CanonicalEvent, EventType, ExplanationPayload, RiskClassification
from driftshield.parsers.claude_code import ClaudeCodeParser


def make_event(**kwargs) -> CanonicalEvent:
    defaults = {
        "id": uuid4(),
        "session_id": "test-session",
        "timestamp": datetime.now(timezone.utc),
        "event_type": EventType.TOOL_CALL,
        "agent_id": "test-agent",
        "action": "test_action",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class CoverageGapExplainer(RiskHeuristic):
    @property
    def name(self) -> str:
        return "coverage_gap"

    def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
        return RiskClassification(
            coverage_gap=True,
            explanations={
                "coverage_gap": ExplanationPayload(
                    reason="Only two of three sections were referenced.",
                    confidence=0.87,
                    evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
                )
            },
        )


class PolicyExplainer(RiskHeuristic):
    @property
    def name(self) -> str:
        return "policy_divergence"

    def check(self, event: CanonicalEvent, context: dict) -> RiskClassification | None:
        return RiskClassification(
            policy_divergence=True,
            explanations={
                "policy_divergence": ExplanationPayload(
                    reason="The output bypassed the approval constraint.",
                    confidence=0.79,
                    evidence_refs=["metadata.policy_rule", "outputs.approval_state"],
                )
            },
        )


def test_risk_analyzer_merges_explanations_across_heuristics() -> None:
    analyzer = RiskAnalyzer(heuristics=[CoverageGapExplainer(), PolicyExplainer()])
    event = make_event()

    [result] = analyzer.analyze([event])

    assert result.risk_classification is not None
    assert result.risk_classification.coverage_gap is True
    assert result.risk_classification.policy_divergence is True
    assert result.risk_classification.explanations == {
        "coverage_gap": ExplanationPayload(
            reason="Only two of three sections were referenced.",
            confidence=0.87,
            evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
        ),
        "policy_divergence": ExplanationPayload(
            reason="The output bypassed the approval constraint.",
            confidence=0.79,
            evidence_refs=["metadata.policy_rule", "outputs.approval_state"],
        ),
    }


def test_analyze_session_emits_inflection_explanation_from_flagged_node() -> None:
    risky_event = make_event(
        action="review_sections",
        inputs={"sections": ["intro", "body", "appendix"]},
        outputs={"reviewed_sections": ["intro", "body"]},
    )
    failure_event = make_event(
        action="deliver_answer",
        event_type=EventType.OUTPUT,
        parent_event_id=risky_event.id,
    )

    result = analyze_session([risky_event, failure_event])

    assert result.inflection_node is not None
    assert result.inflection_node.id == risky_event.id
    assert result.inflection_explanation == ExplanationPayload(
        reason="Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
        confidence=1.0,
        evidence_refs=[f"node:{risky_event.id}", "risk:coverage_gap"],
    )
    assert result.inflection_node.event.risk_classification is not None
    assert result.inflection_node.event.risk_classification.explanations["coverage_gap"] == ExplanationPayload(
        reason="Output referenced fewer items than were provided in the input.",
        confidence=0.86,
        evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
    )


def test_assumption_mutation_explanation_uses_stable_payload_shape() -> None:
    transcript = Path(__file__).parent.parent.parent / "fixtures" / "transcripts" / "dogfood" / "assumption_mutation_session.jsonl"
    events = ClaudeCodeParser().parse_file(str(transcript))

    result = analyze_session(events)

    flagged_event = result.events[-1]
    assert flagged_event.risk_classification is not None
    assert flagged_event.risk_classification.assumption_mutation is True
    assert flagged_event.risk_classification.explanations["assumption_mutation"] == ExplanationPayload(
        reason="An assistant-introduced assumption was carried forward into a new planning step without explicit user instruction.",
        confidence=0.8,
        evidence_refs=["event:1.outputs.result.notes", "event:2.inputs.assumption", "event:2.action:plan_schedule"],
    )


def test_policy_divergence_explanation_uses_stable_payload_shape() -> None:
    transcript = Path(__file__).parent.parent.parent / "fixtures" / "transcripts" / "dogfood" / "policy_divergence_session.jsonl"
    events = ClaudeCodeParser().parse_file(str(transcript))

    result = analyze_session(events)

    flagged_event = result.events[-1]
    assert flagged_event.risk_classification is not None
    assert flagged_event.risk_classification.policy_divergence is True
    assert flagged_event.risk_classification.explanations["policy_divergence"] == ExplanationPayload(
        reason="Action conflicts with a loaded project policy rule.",
        confidence=0.93,
        evidence_refs=["metadata.tool_use_id", "inputs.command", "event:1.outputs.text"],
    )


def test_constraint_violation_explanation_uses_stable_payload_shape() -> None:
    transcript = Path(__file__).parent.parent.parent / "fixtures" / "transcripts" / "dogfood" / "constraint_violation_session.jsonl"
    events = ClaudeCodeParser().parse_file(str(transcript))

    result = analyze_session(events)

    flagged_event = result.events[-1]
    assert flagged_event.risk_classification is not None
    assert flagged_event.risk_classification.constraint_violation is True
    assert flagged_event.risk_classification.explanations["constraint_violation"] == ExplanationPayload(
        reason="Destructive action occurred without required explicit confirmation.",
        confidence=0.95,
        evidence_refs=["metadata.tool_use_id", "inputs.command", "event:1.outputs.text"],
    )
