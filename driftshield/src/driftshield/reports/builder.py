from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from driftshield.core.analysis.session import AnalysisResult
from driftshield.core.graph.models import DecisionNode
from driftshield.core.models import Session as DomainSession
from driftshield.reports.models import (
    EvidenceRef,
    NodeRow,
    PatternMatch,
    ReportData,
    ReportFinding,
    ReportSection,
    ReportSummary,
    ReportType,
    RiskTransition,
)


OSS_SAFETY_NOTE = (
    "This OSS-safe report is built from observable single-run evidence only; it may "
    "identify a visible break-point candidate or local resemblance signals, but it "
    "does not claim decision-grade root cause, causal certainty, or system-level priority."
)


def _rewrite_legacy_mechanism_summary(summary: str) -> str:
    if "OSS-safe signals" in summary:
        return summary

    rewritten = summary.replace("failure families", "failure mechanisms").replace(
        "failure family", "failure mechanism"
    )
    if rewritten.startswith("Matched ") and rewritten.endswith("."):
        return rewritten[:-1] + " from local OSS-safe signals."
    return rewritten


class ReportBuilder:
    def build(
        self,
        session: DomainSession,
        result: AnalysisResult,
        report_type: ReportType = ReportType.FULL,
    ) -> ReportData:
        pattern_matches = self._build_pattern_matches(session)
        findings = self._build_findings(session, result, pattern_matches)
        evidence_index = self._build_evidence_index(session, result, findings, pattern_matches)
        summary = self._build_summary(session, result, pattern_matches)

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
            classification=self._classification_label(result),
            summary=summary,
            findings=findings,
            pattern_matches=pattern_matches,
            evidence_index=evidence_index,
        )

    def _build_lineage_section(self, result: AnalysisResult) -> ReportSection:
        rows = []
        for node in result.graph.nodes:
            risk_flags = []
            rc = node.event.risk_classification
            if rc:
                risk_flags = rc.active_flags()
            rows.append(
                NodeRow(
                    sequence=node.sequence_num,
                    node_id=node.id,
                    event_type=node.event_type.value,
                    action=node.action,
                    risk_flags=risk_flags,
                    is_inflection=(
                        result.inflection_node is not None
                        and node.id == result.inflection_node.id
                    ),
                )
            )
        return ReportSection(
            title="Behavioural Lineage Reconstruction",
            content="Chronological reconstruction of the observable agent decision path.",
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
        for index, node in enumerate(nodes):
            rc = node.event.risk_classification
            if rc and rc.has_any_flag():
                for flag in rc.active_flags():
                    if index + 1 < len(nodes):
                        transitions.append(
                            RiskTransition(
                                from_node_id=node.id,
                                to_node_id=nodes[index + 1].id,
                                risk_type=flag,
                                description=f"{flag} introduced at {node.action}",
                            )
                        )
        return ReportSection(
            title="Risk State Transition Mapping",
            content="How risk flags moved through the visible single-run decision graph.",
            risk_transitions=transitions,
        )

    def _build_exposure_section(self, result: AnalysisResult) -> ReportSection:
        if result.flagged_events == 0:
            classification = "No risk flags were detected in this single run."
        elif result.flagged_events == 1:
            classification = "Isolated: one visible risk point was found in this run."
        else:
            classification = f"Multiple visible risk points ({result.flagged_events} flagged events)."
        return ReportSection(
            title="Single-Run Exposure Assessment",
            content=classification,
        )

    def _build_summary(
        self,
        session: DomainSession,
        result: AnalysisResult,
        pattern_matches: list[PatternMatch],
    ) -> ReportSummary:
        break_point = result.candidate_break_point
        confidence = break_point.confidence if break_point is not None else None
        where_it_broke = self._where_it_broke(result)
        uncertainty = (
            list(break_point.uncertainty_reasons)
            if break_point is not None and break_point.uncertainty_reasons
            else ["only observable single-run evidence was evaluated"]
        )

        event_count = f"{result.total_events} observable {_plural('event', result.total_events)}"
        risk_count = f"{result.flagged_events} risk-flagged {_plural('event', result.flagged_events)}"
        what_happened = (
            f"DriftShield reconstructed {event_count} for a {session.status.value} run "
            f"and found {risk_count}."
        )

        return ReportSummary(
            headline=f"{what_happened} {where_it_broke}",
            what_happened=what_happened,
            where_it_broke=where_it_broke,
            evidence_basis=(
                f"The report cites {len(result.graph.nodes)} lineage "
                f"{_plural('node', len(result.graph.nodes))}, candidate break-point evidence, "
                "and risk explanations where available."
            ),
            confidence=confidence,
            confidence_label=_confidence_label(confidence),
            uncertainty=uncertainty,
            pattern_resemblance=self._pattern_resemblance_summary(pattern_matches, result),
            oss_safety_note=OSS_SAFETY_NOTE,
        )

    def _where_it_broke(self, result: AnalysisResult) -> str:
        break_point = result.candidate_break_point
        if break_point is None:
            return "No candidate break point was available from the observable evidence."
        if break_point.is_identified:
            action = f" ({break_point.action})" if break_point.action else ""
            return f"Visible break-point candidate: event #{break_point.sequence_num}{action}."
        return break_point.summary

    def _build_findings(
        self,
        session: DomainSession,
        result: AnalysisResult,
        pattern_matches: list[PatternMatch],
    ) -> list[ReportFinding]:
        findings = [
            ReportFinding(
                finding_id=f"finding:run_reconstruction:{session.id}",
                finding_kind="run_reconstruction",
                subject_ref=f"session:{session.id}",
                summary=(
                    f"Reconstructed {result.total_events} observable "
                    f"{_plural('event', result.total_events)} with "
                    f"{result.flagged_events} risk-flagged "
                    f"{_plural('event', result.flagged_events)}."
                ),
                evidence_refs=[f"session:{session.id}", f"lineage:{session.id}"],
                confidence=1.0,
            )
        ]

        break_point = result.candidate_break_point
        if break_point is not None:
            findings.append(
                ReportFinding(
                    finding_id=f"finding:candidate_break_point:{session.id}",
                    finding_kind="candidate_break_point",
                    subject_ref=(
                        f"node:{break_point.node_id}"
                        if break_point.node_id is not None
                        else f"session:{session.id}"
                    ),
                    summary=break_point.summary,
                    evidence_refs=(
                        list(break_point.evidence_refs)
                        if break_point.evidence_refs
                        else [f"lineage:{session.id}"]
                    ),
                    confidence=break_point.confidence,
                    status=break_point.status.value,
                )
            )

        if pattern_matches:
            for match in pattern_matches:
                findings.append(
                    ReportFinding(
                        finding_id=f"finding:pattern_resemblance:{match.match_id}",
                        finding_kind="pattern_resemblance",
                        subject_ref=match.scope_ref,
                        summary=_pattern_resemblance_finding_summary(match),
                        evidence_refs=(
                            list(match.evidence_refs)
                            if match.evidence_refs
                            else [f"session:{session.id}"]
                        ),
                        confidence=match.confidence,
                        status="matched",
                    )
                )
        elif active_flags := self._active_risk_flags(result):
            findings.append(
                ReportFinding(
                    finding_id=f"finding:pattern_resemblance:{session.id}",
                    finding_kind="pattern_resemblance",
                    subject_ref=f"session:{session.id}",
                    summary=(
                        "No named OSS-safe pattern match was available, but local risk "
                        f"signals indicate: {', '.join(active_flags)}."
                    ),
                    evidence_refs=[f"risk:{flag}" for flag in active_flags],
                    confidence=break_point.confidence if break_point is not None else None,
                    status="available_as_local_risk_class_only",
                )
            )

        if break_point is not None and not break_point.is_identified:
            findings.append(
                ReportFinding(
                    finding_id=f"finding:evidence_gap:{session.id}",
                    finding_kind="evidence_gap",
                    subject_ref=f"session:{session.id}",
                    summary=(
                        "Observable evidence was not strong enough to isolate a single "
                        "break point."
                    ),
                    evidence_refs=(
                        list(break_point.evidence_refs)
                        if break_point.evidence_refs
                        else [f"lineage:{session.id}"]
                    ),
                    confidence=break_point.confidence,
                    status="open",
                )
            )

        return findings

    def _build_pattern_matches(self, session: DomainSession) -> list[PatternMatch]:
        metadata = session.metadata if isinstance(session.metadata, Mapping) else {}
        payload = metadata.get("signature_match") or metadata.get("signature_summary")
        if not isinstance(payload, Mapping):
            return []

        raw_matches = payload.get("matches")
        if isinstance(raw_matches, list):
            candidates = raw_matches
        else:
            candidates = [payload]

        matches: list[PatternMatch] = []
        for index, item in enumerate(candidates, start=1):
            if not isinstance(item, Mapping):
                continue
            matches.extend(self._pattern_matches_from_payload(session, item, index))
        return matches

    def _pattern_matches_from_payload(
        self,
        session: DomainSession,
        payload: Mapping[str, Any],
        index: int,
    ) -> list[PatternMatch]:
        signature_id = _string_value(payload.get("signature_id"))
        mechanism_id = _string_value(
            payload.get("mechanism_id")
            or payload.get("family_id")
            or payload.get("primary_mechanism_id")
            or payload.get("primary_family_id")
        )
        mechanism_ids = _ordered_mechanism_ids(payload)
        if mechanism_id is not None and mechanism_id not in mechanism_ids:
            mechanism_ids.insert(0, mechanism_id)

        if signature_id is None and not mechanism_ids:
            return []

        signature_layer = (
            dict(payload.get("signature_layer"))
            if isinstance(payload.get("signature_layer"), Mapping)
            else {}
        )
        rationale = _string_value(payload.get("rationale") or payload.get("summary")) or ""
        if rationale:
            rationale = _rewrite_legacy_mechanism_summary(rationale)
        if rationale and "symptom" not in signature_layer:
            signature_layer["symptom"] = rationale
        evidence_refs = _string_list(
            payload.get("evidence_refs") or payload.get("evidence_event_refs")
        )
        scope_ref = _string_value(payload.get("scope_ref")) or f"session:{session.id}"
        confidence = _float_value(payload.get("confidence"))
        source = _string_value(payload.get("source")) or "local"
        match_id = _string_value(payload.get("match_id")) or f"pattern_match:{session.id}:{index}"

        if signature_id is not None:
            resolved_mechanism_id = mechanism_id or (mechanism_ids[0] if mechanism_ids else None)
            if resolved_mechanism_id is None:
                return []
            return [
                PatternMatch(
                    match_id=match_id,
                    signature_id=signature_id,
                    mechanism_id=resolved_mechanism_id,
                    signature_layer=signature_layer,
                    scope_ref=scope_ref,
                    evidence_refs=evidence_refs,
                    confidence=confidence,
                    rationale=rationale,
                    source=source,
                )
            ]

        matches: list[PatternMatch] = []
        for mechanism_offset, derived_mechanism_id in enumerate(mechanism_ids, start=1):
            matches.append(
                PatternMatch(
                    match_id=f"{match_id}:{mechanism_offset}",
                    signature_id=f"mechanism:{derived_mechanism_id}",
                    mechanism_id=derived_mechanism_id,
                    signature_layer=dict(signature_layer),
                    scope_ref=scope_ref,
                    evidence_refs=evidence_refs,
                    confidence=confidence,
                    rationale=rationale,
                    source=source,
                )
            )
        return matches

    def _pattern_resemblance_summary(
        self,
        pattern_matches: list[PatternMatch],
        result: AnalysisResult,
    ) -> str:
        if pattern_matches:
            mechanisms = ", ".join(match.mechanism_id for match in pattern_matches)
            return f"Local OSS-safe pattern signals resemble: {mechanisms}."

        active_flags = self._active_risk_flags(result)
        if active_flags:
            return (
                "No named OSS-safe pattern match was available; local risk signals "
                f"include: {', '.join(active_flags)}."
            )

        return "No local pattern resemblance was available from OSS-safe signals."

    def _build_evidence_index(
        self,
        session: DomainSession,
        result: AnalysisResult,
        findings: list[ReportFinding],
        pattern_matches: list[PatternMatch],
    ) -> list[EvidenceRef]:
        index: dict[str, EvidenceRef] = {}

        def add(ref: EvidenceRef) -> None:
            if ref.ref_id not in index:
                index[ref.ref_id] = ref

        add(
            EvidenceRef(
                ref_id=f"session:{session.id}",
                target_kind="analysis_session",
                target_ref=str(session.id),
                role="session",
                excerpt=f"{session.status.value} run for {session.agent_id}",
            )
        )
        add(
            EvidenceRef(
                ref_id=f"lineage:{session.id}",
                target_kind="lineage_graph",
                target_ref=str(session.id),
                role="lineage",
                excerpt=_lineage_excerpt(result),
            )
        )

        for node in result.graph.nodes:
            add(self._node_evidence_ref(node))
            for flag in _node_risk_flags(node):
                add(
                    EvidenceRef(
                        ref_id=f"risk:{flag}",
                        target_kind="finding",
                        target_ref=flag,
                        role="risk_signal",
                        excerpt=f"Risk signal active on event #{node.sequence_num}.",
                    )
                )

        for finding in findings:
            for token in finding.evidence_refs:
                add(self._evidence_ref_from_token(token, session, result))

        for match in pattern_matches:
            for token in match.evidence_refs:
                add(self._evidence_ref_from_token(token, session, result))

        return list(index.values())

    def _evidence_ref_from_token(
        self,
        token: str,
        session: DomainSession,
        result: AnalysisResult,
    ) -> EvidenceRef:
        if token == f"session:{session.id}":
            return EvidenceRef(
                ref_id=token,
                target_kind="analysis_session",
                target_ref=str(session.id),
                role="session",
                excerpt=f"{session.status.value} run for {session.agent_id}",
            )

        if token == f"lineage:{session.id}":
            return EvidenceRef(
                ref_id=token,
                target_kind="lineage_graph",
                target_ref=str(session.id),
                role="lineage",
                excerpt=_lineage_excerpt(result),
            )

        if token.startswith("node:"):
            node_id = token.removeprefix("node:")
            node = _node_by_id(result, node_id)
            if node is not None:
                return self._node_evidence_ref(node)
            return EvidenceRef(
                ref_id=token,
                target_kind="decision_node",
                target_ref=node_id,
                role="lineage_node",
            )

        if token.startswith("risk:"):
            risk_flag = token.removeprefix("risk:")
            return EvidenceRef(
                ref_id=token,
                target_kind="finding",
                target_ref=risk_flag,
                role="risk_signal",
                excerpt=f"Risk signal: {risk_flag}.",
            )

        if token.startswith("inflection_reason:"):
            reason = token.removeprefix("inflection_reason:")
            return EvidenceRef(
                ref_id=token,
                target_kind="analysis_reason",
                target_ref=reason,
                role="selection_reason",
                excerpt=reason,
            )

        if token.startswith("event:"):
            return EvidenceRef(
                ref_id=token,
                target_kind="normalized_event",
                target_ref=token,
                role="event_evidence",
            )

        if "." in token:
            return EvidenceRef(
                ref_id=token,
                target_kind="normalized_event_field",
                target_ref=token,
                role="field_evidence",
                excerpt=token,
            )

        return EvidenceRef(
            ref_id=token,
            target_kind="analysis_evidence",
            target_ref=token,
            role="supporting_evidence",
        )

    def _node_evidence_ref(self, node: DecisionNode) -> EvidenceRef:
        summary = node.summary or node.action
        return EvidenceRef(
            ref_id=f"node:{node.id}",
            target_kind="decision_node",
            target_ref=str(node.id),
            role="lineage_node",
            excerpt=f"Event #{node.sequence_num}: {summary}",
            metadata={
                "sequence_num": node.sequence_num,
                "event_type": node.event_type.value,
                "risk_flags": _node_risk_flags(node),
                "lineage_ambiguities": list(node.lineage_ambiguities),
            },
        )

    def _active_risk_flags(self, result: AnalysisResult) -> list[str]:
        return [
            flag
            for flag, count in result.risk_summary.items()
            if count > 0
        ]

    def _classification_label(self, result: AnalysisResult) -> str:
        if result.flagged_events == 0:
            return "no_risk_flags"
        if result.flagged_events == 1:
            return "isolated"
        return "multiple_visible_risk_points"


def _confidence_label(confidence: float | None) -> str:
    if confidence is None:
        return "unknown"
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _plural(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"


def _ordered_mechanism_ids(payload: Mapping[str, Any]) -> list[str]:
    ordered: list[str] = []

    primary_mechanism_id = _string_value(
        payload.get("primary_mechanism_id") or payload.get("primary_family_id")
    )
    if primary_mechanism_id is not None:
        ordered.append(primary_mechanism_id)

    matched_mechanism_ids = payload.get("matched_mechanism_ids")
    if not isinstance(matched_mechanism_ids, list):
        matched_mechanism_ids = payload.get("matched_family_ids")
    if isinstance(matched_mechanism_ids, list):
        for item in matched_mechanism_ids:
            mechanism_id = _string_value(item)
            if mechanism_id is not None and mechanism_id not in ordered:
                ordered.append(mechanism_id)

    return ordered


def _pattern_resemblance_finding_summary(match: PatternMatch) -> str:
    if match.signature_id.startswith("mechanism:"):
        return f"Local OSS-safe signals resemble {match.mechanism_id}."
    return f"Local OSS-safe signals resemble {match.mechanism_id} via {match.signature_id}."


def _lineage_excerpt(result: AnalysisResult) -> str:
    node_count = len(result.graph.nodes)
    edge_count = len(result.graph.edges)
    return (
        f"{node_count} {_plural('node', node_count)} and "
        f"{edge_count} {_plural('edge', edge_count)}"
    )


def _node_risk_flags(node: DecisionNode) -> list[str]:
    risk = node.event.risk_classification
    return risk.active_flags() if risk is not None else []


def _node_by_id(result: AnalysisResult, value: str) -> DecisionNode | None:
    try:
        node_id = UUID(value)
    except ValueError:
        return None

    return result.graph.get_node(node_id)


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
