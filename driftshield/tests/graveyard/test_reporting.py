import json

from driftshield.graveyard.reporting import build_report


def test_build_report_summarises_candidates_by_signal_and_likelihood(tmp_path):
    candidates = [
        {
            "repo": "langchain-ai/langchain",
            "issue_number": 1,
            "issue_url": "https://github.com/langchain-ai/langchain/issues/1",
            "title": "Agent ignored tool error",
            "score": 9,
            "likelihood": "high",
            "signals": ["agent", "tool_call", "agentic_failure"],
            "evidence_text": "...",
        },
        {
            "repo": "microsoft/autogen",
            "issue_number": 2,
            "issue_url": "https://github.com/microsoft/autogen/issues/2",
            "title": "Context contamination in chain",
            "score": 7,
            "likelihood": "high",
            "signals": ["reasoning_flow", "agentic_failure"],
            "evidence_text": "...",
        },
        {
            "repo": "crewAIInc/crewAI",
            "issue_number": 3,
            "issue_url": "https://github.com/crewAIInc/crewAI/issues/3",
            "title": "Possible drift",
            "score": 5,
            "likelihood": "medium",
            "signals": ["agent", "reasoning_flow"],
            "evidence_text": "...",
        },
    ]

    input_path = tmp_path / "candidates.jsonl"
    with input_path.open("w", encoding="utf-8") as f:
        for row in candidates:
            f.write(json.dumps(row) + "\n")

    report = build_report(input_path)

    assert report.total_candidates == 3
    assert report.by_likelihood["high"] == 2
    assert report.by_likelihood["medium"] == 1
    signal_names = [name for name, _ in report.top_signals]
    assert "agentic_failure" in signal_names
    assert report.by_repo["langchain-ai/langchain"] == 1
