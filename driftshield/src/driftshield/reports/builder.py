from datetime import datetime, timezone

from driftshield.core.models import Session as DomainSession
from driftshield.core.analysis.session import AnalysisResult
from driftshield.reports.models import (
    ReportData, ReportSection, ReportType, NodeRow, RiskTransition,
)


class ReportBuilder:
    def build(
        self,
        session: DomainSession,
        result: AnalysisResult,
        report_type: ReportType = ReportType.FULL,
    ) -> ReportData:
        sections = [
            self._build_lineage_section(result),
            self._build_inflection_section(result),
        ]
        if report_type == ReportType.FULL:
            sections.extend(
                [
                    self._build_risk_transition_section(result),
                    self._build_exposure_section(result),
                ]
            )

        return ReportData(
            session_id=session.id,
            agent_id=session.agent_id,
            generated_at=datetime.now(timezone.utc),
            report_type=report_type,
            sections=sections,
            inflection_node_id=(
                result.inflection_node.id if result.inflection_node else None
            ),
            inflection_action=(
                result.inflection_node.action if result.inflection_node else None
            ),
            candidate_break_point=result.candidate_break_point,
            total_events=result.total_events,
            flagged_events=result.flagged_events,
        )

    def _build_lineage_section(self, result: AnalysisResult) -> ReportSection:
        rows = []
        for node in result.graph.nodes:
            risk_flags = []
            rc = node.event.risk_classification
            if rc:
                risk_flags = rc.active_flags()
            rows.append(NodeRow(
                sequence=node.sequence_num,
                node_id=node.id,
                event_type=node.event_type.value,
                action=node.action,
                risk_flags=risk_flags,
                is_inflection=(
                    result.inflection_node is not None
                    and node.id == result.inflection_node.id
                ),
            ))
        return ReportSection(
            title="Behavioural Lineage Reconstruction",
            content="Chronological reconstruction of the agent's decision path.",
            node_table=rows,
        )

    def _build_inflection_section(self, result: AnalysisResult) -> ReportSection:
        if result.candidate_break_point and result.candidate_break_point.is_identified:
            break_point = result.candidate_break_point
            content = (
                f"{break_point.summary} Confidence {break_point.confidence:.2f}."
                if break_point.confidence is not None
                else break_point.summary
            )
            if break_point.uncertainty_reasons:
                content += " Uncertainty: " + "; ".join(break_point.uncertainty_reasons) + "."
        elif result.candidate_break_point:
            break_point = result.candidate_break_point
            content = break_point.summary
            if break_point.uncertainty_reasons:
                content += " Uncertainty: " + "; ".join(break_point.uncertainty_reasons) + "."
        elif result.inflection_node:
            content = (
                f"Observable evidence suggests the run visibly broke at event "
                f"#{result.inflection_node.sequence_num} ({result.inflection_node.action})."
            )
        else:
            content = "No clear break point detected from observable run evidence."
        return ReportSection(
            title="Candidate Break Point Assessment",
            content=content,
        )

    def _build_risk_transition_section(self, result: AnalysisResult) -> ReportSection:
        transitions = []
        nodes = result.graph.nodes
        for i, node in enumerate(nodes):
            rc = node.event.risk_classification
            if rc and rc.has_any_flag():
                for flag in rc.active_flags():
                    if i + 1 < len(nodes):
                        transitions.append(RiskTransition(
                            from_node_id=node.id,
                            to_node_id=nodes[i + 1].id,
                            risk_type=flag,
                            description=f"{flag} introduced at {node.action}",
                        ))
        return ReportSection(
            title="Risk State Transition Mapping",
            content="How risk propagated through the decision graph.",
            risk_transitions=transitions,
        )

    def _build_exposure_section(self, result: AnalysisResult) -> ReportSection:
        if result.flagged_events == 0:
            classification = "No risk flags detected."
        elif result.flagged_events == 1:
            classification = "Isolated: single point of risk in the decision path."
        else:
            classification = f"Multiple risk points ({result.flagged_events} flagged events)."
        return ReportSection(
            title="Systemic Exposure Assessment",
            content=classification,
        )
