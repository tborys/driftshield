"""Inspect command for DriftShield CLI."""

import json
import os
from pathlib import Path

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser
from driftshield.cli.discovery import resolve_session
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode, LineageGraph


console = Console(force_terminal=True)


def format_node_detail(node: DecisionNode, graph: LineageGraph) -> str:
    """Format a node for detailed display."""
    lines = [
        f"Node #{node.sequence_num}: {node.action}",
        "\u2500" * 30,
        f"Type:      {node.event_type.value}",
        f"Timestamp: {node.event.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Agent:     {node.event.agent_id}",
    ]

    if node.inputs:
        lines.append("")
        lines.append("Inputs:")
        for key, value in list(node.inputs.items())[:5]:
            val_str = str(value)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            lines.append(f"  {key}: {val_str}")

    if node.outputs:
        lines.append("")
        lines.append("Outputs:")
        for key, value in list(node.outputs.items())[:5]:
            val_str = str(value)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            lines.append(f"  {key}: {val_str}")

    if node.has_risk_flags() and node.event.risk_classification:
        lines.append("")
        lines.append("Risk Flags:")
        for flag in node.event.risk_classification.active_flags():
            lines.append(f"  \u26a0 {flag}")

    lines.append("")
    parent = graph.get_parent(node.id)
    if parent:
        lines.append(f"Parent: #{parent.sequence_num} ({parent.action})")
    else:
        lines.append("Parent: (root)")

    children = graph.get_children(node.id)
    if children:
        child_strs = [f"#{c.sequence_num} ({c.action})" for c in children]
        lines.append(f"Children: {', '.join(child_strs)}")

    return "\n".join(lines)


def format_path_to_root(path: list[DecisionNode]) -> str:
    """Format path to root display."""
    lines = [f"Path to Root from Node #{path[0].sequence_num}", "\u2500" * 30]

    for i, node in enumerate(path):
        flags = ""
        if node.has_risk_flags() and node.event.risk_classification:
            flags = "   \u26a0 " + ", ".join(node.event.risk_classification.active_flags())

        suffix = " (root)" if i == len(path) - 1 else ""
        lines.append(f"#{node.sequence_num} {node.action}{flags}{suffix}")

        if i < len(path) - 1:
            lines.append(" \u2191")

    return "\n".join(lines)


def inspect(
    session: str = typer.Argument(
        ...,
        help="Session file path or session ID.",
    ),
    node: int = typer.Option(
        ...,
        "--node",
        "-n",
        help="Node number to inspect.",
    ),
    path_to_root: bool = typer.Option(
        False,
        "--path-to-root",
        help="Show path from node to root.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
) -> None:
    """Inspect a specific node in a session."""
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    resolved = resolve_session(session, Path.cwd(), claude_base)
    if resolved is None:
        direct = Path(session).expanduser().resolve()
        if direct.exists():
            resolved = direct
        else:
            console.print(f"[red]Error:[/red] Could not find session: {session}")
            raise typer.Exit(1)

    parser_name = detect_parser(resolved)
    if parser_name is None:
        console.print(f"[red]Error:[/red] Could not detect parser for: {resolved.name}")
        raise typer.Exit(1)

    parser = get_parser(parser_name)
    events = parser.parse_file(str(resolved))

    if not events:
        console.print("[red]Error:[/red] No events found in session.")
        raise typer.Exit(1)

    graph = build_graph(events, session_id=events[0].session_id)

    target_node = None
    for n in graph.nodes:
        if n.sequence_num == node:
            target_node = n
            break

    if target_node is None:
        console.print(
            f"[red]Error:[/red] Node #{node} not found. "
            f"Session has {len(graph.nodes)} nodes (0-{len(graph.nodes) - 1})."
        )
        raise typer.Exit(1)

    if json_output:
        data = {
            "node": node,
            "action": target_node.action,
            "type": target_node.event_type.value,
            "timestamp": target_node.event.timestamp.isoformat(),
            "agent_id": target_node.event.agent_id,
            "inputs": target_node.inputs,
            "outputs": target_node.outputs,
            "has_risk_flags": target_node.has_risk_flags(),
            "risk_flags": (
                target_node.event.risk_classification.active_flags()
                if target_node.event.risk_classification
                else []
            ),
        }
        if path_to_root:
            path = graph.path_to_root(target_node.id)
            data["path_to_root"] = [
                {"node": n.sequence_num, "action": n.action}
                for n in path
            ]
        console.print(json.dumps(data, indent=2, default=str))
    elif path_to_root:
        path = graph.path_to_root(target_node.id)
        console.print(format_path_to_root(path))
    else:
        console.print(format_node_detail(target_node, graph))
