from typing import Any

from driftshield.reports.models import ReportData


def export_json(report: ReportData) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "session_id": str(report.session_id),
        "agent_id": report.agent_id,
        "generated_at": report.generated_at.isoformat(),
        "report_type": report.report_type.value,
        "total_events": report.total_events,
        "flagged_events": report.flagged_events,
        "summary": {
            "headline": report.summary.headline,
            "what_happened": report.summary.what_happened,
            "where_it_broke": report.summary.where_it_broke,
            "evidence_basis": report.summary.evidence_basis,
            "confidence": report.summary.confidence,
            "confidence_label": report.summary.confidence_label,
            "uncertainty": list(report.summary.uncertainty),
            "pattern_resemblance": report.summary.pattern_resemblance,
            "oss_safety_note": report.summary.oss_safety_note,
        },
        "findings": [
            {
                "finding_id": finding.finding_id,
                "finding_kind": finding.finding_kind,
                "subject_ref": finding.subject_ref,
                "summary": finding.summary,
                "evidence_refs": list(finding.evidence_refs),
                "confidence": finding.confidence,
                "status": finding.status,
            }
            for finding in report.findings
        ],
        "pattern_matches": [
            {
                "match_id": match.match_id,
                "signature_id": match.signature_id,
                "mechanism_id": match.mechanism_id,
                "signature_layer": dict(match.signature_layer),
                "scope_ref": match.scope_ref,
                "evidence_refs": list(match.evidence_refs),
                "confidence": match.confidence,
                "rationale": match.rationale,
                "source": match.source,
            }
            for match in report.pattern_matches
        ],
        "evidence_index": [
            {
                "ref_id": ref.ref_id,
                "target_kind": ref.target_kind,
                "target_ref": ref.target_ref,
                "role": ref.role,
                "excerpt": ref.excerpt,
                "metadata": dict(ref.metadata),
            }
            for ref in report.evidence_index
        ],
        "candidate_break_point": (
            report.candidate_break_point.to_dict()
            if report.candidate_break_point is not None
            else None
        ),
        "inflection_node_id": str(report.inflection_node_id) if report.inflection_node_id else None,
        "inflection_action": report.inflection_action,
        "classification": report.classification,
        "integrity_snapshot": report.integrity_snapshot,
        "sections": [
            {
                "title": s.title,
                "content": s.content,
                "node_table": [
                    {
                        "sequence": row.sequence,
                        "node_id": str(row.node_id),
                        "event_type": row.event_type,
                        "action": row.action,
                        "risk_flags": row.risk_flags,
                        "is_inflection": row.is_inflection,
                    }
                    for row in s.node_table
                ],
                "risk_transitions": [
                    {
                        "from_node_id": str(t.from_node_id),
                        "to_node_id": str(t.to_node_id),
                        "risk_type": t.risk_type,
                        "description": t.description,
                    }
                    for t in s.risk_transitions
                ],
            }
            for s in report.sections
        ],
    }
