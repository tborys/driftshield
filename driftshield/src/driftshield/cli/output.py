"""Output formatters for CLI."""

import json
from typing import Any

from rich.console import Console
from rich.table import Table

from driftshield.core.analysis.session import AnalysisResult


def format_summary(result: AnalysisResult) -> str:
    """Format analysis result as summary text."""
    lines = [
        "DriftShield Analysis",
        "\u2500" * 20,
        f"Session: {result.graph.session_id}",
        f"Events:  {result.total_events}",
        f"Flagged: {result.flagged_events}",
    ]

    if result.has_risks:
        lines.append("")
        lines.append("Risks Detected:")
        for risk_type, count in result.risk_summary.items():
            if count > 0:
                lines.append(f"  - {risk_type}: {count}")

    if result.inflection_node:
        node = result.inflection_node
        lines.append("")
        lines.append("Inflection Point:")
        lines.append(f"  Event #{node.sequence_num} : {node.action}")
        lines.append(f"  Type      : {node.event_type.value}")

        if node.event.risk_classification:
            flags = ", ".join(node.event.risk_classification.active_flags())
            lines.append(f"  Risk      : {flags}")

    return "\n".join(lines)


def format_json(result: AnalysisResult) -> str:
    """Format analysis result as JSON."""
    data: dict[str, Any] = {
        "session_id": result.graph.session_id,
        "total_events": result.total_events,
        "flagged_events": result.flagged_events,
        "risks": result.risk_summary,
    }

    if result.inflection_node:
        node = result.inflection_node
        data["inflection"] = {
            "event_index": node.sequence_num,
            "action": node.action,
            "flags": (
                node.event.risk_classification.active_flags()
                if node.event.risk_classification
                else []
            ),
        }
    else:
        data["inflection"] = None

    data["events"] = [
        {
            "index": i,
            "action": e.action,
            "type": e.event_type.value,
            "has_flags": e.has_risk_flags(),
        }
        for i, e in enumerate(result.events)
    ]

    return json.dumps(data, indent=2)


def format_verbose_table(result: AnalysisResult) -> str:
    """Format analysis result as verbose table."""
    console = Console(force_terminal=True, width=100)

    table = Table(title="Events")
    table.add_column("#", style="dim", width=4)
    table.add_column("Action", width=30)
    table.add_column("Type", width=15)
    table.add_column("Flags", width=25)

    for i, event in enumerate(result.events):
        flags = ""
        if event.has_risk_flags() and event.risk_classification:
            flags = "\u26a0 " + ", ".join(event.risk_classification.active_flags())

        table.add_row(
            str(i),
            event.action[:28] + ".." if len(event.action) > 30 else event.action,
            event.event_type.value,
            flags,
        )

    with console.capture() as capture:
        console.print(table)

    return capture.get()


def format_quiet(result: AnalysisResult) -> str:
    """Format analysis result as minimal output."""
    if result.flagged_events == 0:
        return "\u2713 No risks detected"
    else:
        return f"\u26a0 {result.flagged_events} risk(s) detected"
