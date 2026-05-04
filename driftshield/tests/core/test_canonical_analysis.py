from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.analysis.session import analyze_session
from driftshield.core.canonical_analysis import build_canonical_analysis
from driftshield.core.models import CanonicalEvent, EventType, Session, SessionStatus
from driftshield.core.normalization import normalize_events
from driftshield.parsers.claude_code import ClaudeCodeParser


def test_build_canonical_analysis_emits_result_families_for_completed_tool_calls():
    transcript = "\n".join(
        [
            '{"sessionId":"canonical-1","type":"assistant","timestamp":"2026-05-04T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tool_1","name":"Read","input":{"file_path":"README.md"}}]}}',
            '{"sessionId":"canonical-1","type":"user","timestamp":"2026-05-04T12:00:01Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool_1","content":"file contents here","is_error":false}]}}',
        ]
    )
    events = ClaudeCodeParser().parse(transcript)
    result = analyze_session(events)

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    families = [event["event_family"] for event in payload["normalized_events"]]
    assert "state_read" in families
    assert "tool_result" in families
    assert "tool_result" not in payload["extraction_quality_summary"]["missing_event_families"]

    result_event = next(
        event for event in payload["normalized_events"] if event["event_family"] == "tool_result"
    )
    assert result_event["causal_parents"] == [payload["normalized_events"][0]["event_id"]]
    assert result_event["structured_payload"]["invocation_id"] == "tool_1"
    assert result_event["structured_payload"]["result_status"] == "completed"


def test_build_canonical_analysis_preserves_developer_constraints_from_instruction_artifacts():
    event = CanonicalEvent(
        id=uuid4(),
        session_id="canonical-2",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="claude",
        action="Read",
        inputs={"file_path": "/tmp/.openclaw/SOUL.md"},
        outputs={"result": "You must verify changes before replying."},
        metadata={"tool_use_id": "tool_2", "semantic_action_category": "file_io"},
    )
    events = normalize_events([event], source_type="claude_code")
    result = analyze_session(events)

    payload = build_canonical_analysis(
        session=Session(
            id=uuid4(),
            agent_id="claude",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result=result,
        provenance=None,
    )

    developer_constraints = payload["policy_and_instruction_context"]["developer_constraints"]
    assert developer_constraints
    assert developer_constraints[0]["constraint"] == "You must verify changes before replying."
    assert developer_constraints[0]["observed_via"] == "inferred_from_instruction_artifact"
