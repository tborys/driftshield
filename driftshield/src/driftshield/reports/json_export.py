from typing import Any

from driftshield.reports.models import ReportData


def export_json(report: ReportData) -> dict[str, Any]:
    return {
        "session_id": str(report.session_id),
        "agent_id": report.agent_id,
        "generated_at": report.generated_at.isoformat(),
        "report_type": report.report_type.value,
        "total_events": report.total_events,
        "flagged_events": report.flagged_events,
        "inflection_node_id": str(report.inflection_node_id) if report.inflection_node_id else None,
        "inflection_action": report.inflection_action,
        "classification": report.classification,
        "recurrence_probability": report.recurrence_probability,
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
