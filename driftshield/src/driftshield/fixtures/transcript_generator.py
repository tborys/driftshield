"""Generate deterministic Claude Code-style JSONL transcripts from scenario fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from driftshield.core.graph.models import LineageGraph
from driftshield.core.models import CanonicalEvent, EventType
from tests.fixtures.scenarios import (
    assumption_introduction_scenario,
    coverage_gap_scenario,
    cross_tool_contamination_scenario,
)

ScenarioFn = Callable[[], tuple[LineageGraph, dict]]


@dataclass(slots=True)
class ScenarioSpec:
    name: str
    scenario_fn: ScenarioFn


class ScenarioTranscriptGenerator:
    def __init__(self, scenarios: list[ScenarioSpec]) -> None:
        self._scenarios = scenarios

    def generate(self, output_dir: Path, include_clean: bool = False) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        for spec in self._scenarios:
            graph, _meta = spec.scenario_fn()
            events = [node.event for node in graph.nodes]
            path = output_dir / f"{spec.name}.jsonl"
            path.write_text(self._to_jsonl(events), encoding="utf-8")
            written.append(path)

        if include_clean:
            clean_events = self._clean_events()
            path = output_dir / "clean_session.jsonl"
            path.write_text(self._to_jsonl(clean_events), encoding="utf-8")
            written.append(path)

        return written

    def _to_jsonl(self, events: list[CanonicalEvent]) -> str:
        lines: list[str] = []
        session_id = events[0].session_id if events else "fixture"

        for index, event in enumerate(events):
            tool_use_id = f"toolu_fixture_{index}"
            lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": session_id,
                        "timestamp": event.timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "message": {
                            "model": "fixture-generator",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": tool_use_id,
                                    "name": event.action,
                                    "input": event.inputs,
                                }
                            ],
                        },
                    },
                    sort_keys=True,
                )
            )
            lines.append(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": session_id,
                        "timestamp": event.timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": json.dumps(event.outputs, sort_keys=True),
                                    "is_error": False,
                                }
                            ]
                        },
                    },
                    sort_keys=True,
                )
            )

        return "\n".join(lines) + "\n"

    def _clean_events(self) -> list[CanonicalEvent]:
        now = datetime.now(timezone.utc)
        return [
            CanonicalEvent(
                id=__import__("uuid").uuid4(),
                session_id="clean-session-001",
                timestamp=now,
                event_type=EventType.TOOL_CALL,
                agent_id="fixture",
                action="retrieve_data",
                inputs={"query": "status"},
                outputs={"status": "ok"},
            ),
            CanonicalEvent(
                id=__import__("uuid").uuid4(),
                session_id="clean-session-001",
                timestamp=now,
                event_type=EventType.OUTPUT,
                agent_id="fixture",
                action="output",
                inputs={},
                outputs={"message": "all checks passed"},
            ),
        ]


def default_scenario_registry() -> list[ScenarioSpec]:
    return [
        ScenarioSpec(name="coverage_gap", scenario_fn=coverage_gap_scenario),
        ScenarioSpec(name="assumption_introduction", scenario_fn=assumption_introduction_scenario),
        ScenarioSpec(name="cross_tool_contamination", scenario_fn=cross_tool_contamination_scenario),
    ]
