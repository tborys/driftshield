from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class GraveyardReport:
    total_candidates: int
    by_likelihood: dict[str, int]
    by_repo: dict[str, int]
    top_signals: list[tuple[str, int]]


def build_report(path: Path) -> GraveyardReport:
    by_likelihood: Counter[str] = Counter()
    by_repo: Counter[str] = Counter()
    signals: Counter[str] = Counter()
    total = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            total += 1
            by_likelihood[row.get("likelihood", "unknown")] += 1
            by_repo[row.get("repo", "unknown")] += 1
            for signal in row.get("signals", []):
                signals[signal] += 1

    return GraveyardReport(
        total_candidates=total,
        by_likelihood=dict(by_likelihood),
        by_repo=dict(by_repo),
        top_signals=signals.most_common(10),
    )


def to_markdown(report: GraveyardReport) -> str:
    lines = [
        "# State of OSS Agent Failures (Spike)",
        "",
        f"- Total candidate threads: **{report.total_candidates}**",
        "",
        "## By Likelihood",
    ]
    for key, value in sorted(report.by_likelihood.items()):
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## By Repo"])
    for repo, count in sorted(report.by_repo.items()):
        lines.append(f"- {repo}: {count}")

    lines.extend(["", "## Top Signals"])
    for signal, count in report.top_signals:
        lines.append(f"- {signal}: {count}")

    return "\n".join(lines) + "\n"
