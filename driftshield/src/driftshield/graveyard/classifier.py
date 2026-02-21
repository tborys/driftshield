import re

from driftshield.graveyard.models import ClassificationResult

_POSITIVE_RULES: list[tuple[str, str, int]] = [
    (r"\bagent\b", "agent", 2),
    (r"\b(prompt|context window|reasoning|chain)\b", "reasoning_flow", 2),
    (r"\btool\b", "tool_call", 2),
    (r"\b(hallucinat|drift|mis-sequenc|wrong output|ignored error)\b", "agentic_failure", 3),
    (r"```", "trace_block", 2),
    (r"(traceback|stack trace|exception)", "error_trace", 1),
    (r"\b(crm|payment|claim|system of record)\b", "write_path", 2),
]

_NEGATIVE_RULES: list[tuple[str, str, int]] = [
    (r"\b(css|button|frontend|ui)\b", "ui_bug", -2),
    (r"\b(build fail|import error|pip install|dependency)\b", "build_bug", -2),
    (r"\b(typo|docs only|readme)\b", "docs", -1),
]


def classify_thread(title: str, text: str) -> ClassificationResult:
    blob = f"{title}\n{text}".lower()
    score = 0
    signals: list[str] = []

    for pattern, name, weight in _POSITIVE_RULES:
        if re.search(pattern, blob):
            score += weight
            signals.append(name)

    for pattern, name, weight in _NEGATIVE_RULES:
        if re.search(pattern, blob):
            score += weight
            signals.append(name)

    if score >= 7:
        likelihood = "high"
        is_candidate = True
    elif score >= 4:
        likelihood = "medium"
        is_candidate = True
    else:
        likelihood = "low"
        is_candidate = False

    return ClassificationResult(
        score=score,
        likelihood=likelihood,
        is_candidate=is_candidate,
        signals=signals,
    )
