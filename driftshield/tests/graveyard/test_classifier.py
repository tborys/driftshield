from driftshield.graveyard.classifier import classify_thread


def test_classify_agentic_failure_thread_high_confidence() -> None:
    title = "Agent ignores tool error and keeps going"
    body = """
The agent called the calculator tool and got schema mismatch.
Then it hallucinated a fallback and wrote wrong output.
Trace:
```json
{"step": 1, "tool": "calculator", "error": "schema mismatch"}
```
"""
    result = classify_thread(title, body)

    assert result.is_candidate is True
    assert result.likelihood == "high"
    assert "tool_call" in result.signals


def test_classify_non_agentic_bug_thread_low_confidence() -> None:
    title = "Build fails on Python 3.12"
    body = "pip install error and import failure, no agent flow involved"

    result = classify_thread(title, body)

    assert result.is_candidate is False
    assert result.likelihood == "low"
