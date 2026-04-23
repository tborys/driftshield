"""Tests for core domain models."""

from datetime import datetime, timezone
from uuid import uuid4

from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    RiskClassification,
    Session,
    SessionStatus,
)
from driftshield.core.normalization import normalize_events


class TestEventType:
    def test_event_type_values_exist(self):
        """All expected event types are defined."""
        assert EventType.TOOL_CALL.value == "TOOL_CALL"
        assert EventType.BRANCH.value == "BRANCH"
        assert EventType.CONSTRAINT_CHECK.value == "CONSTRAINT_CHECK"
        assert EventType.ASSUMPTION.value == "ASSUMPTION"
        assert EventType.HANDOFF.value == "HANDOFF"
        assert EventType.OUTPUT.value == "OUTPUT"

    def test_event_type_is_string_enum(self):
        """EventType values are strings for JSON serialization."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)


class TestRiskClassification:
    def test_default_values_are_false(self):
        """All risk flags default to False."""
        risk = RiskClassification()
        assert risk.assumption_mutation is False
        assert risk.policy_divergence is False
        assert risk.constraint_violation is False
        assert risk.context_contamination is False
        assert risk.coverage_gap is False

    def test_can_set_individual_flags(self):
        """Individual flags can be set to True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        assert risk.assumption_mutation is True
        assert risk.policy_divergence is False
        assert risk.coverage_gap is True

    def test_has_any_flag(self):
        """has_any_flag returns True if any flag is set."""
        assert RiskClassification().has_any_flag() is False
        assert RiskClassification(assumption_mutation=True).has_any_flag() is True
        assert RiskClassification(coverage_gap=True).has_any_flag() is True

    def test_active_flags_returns_set_flags(self):
        """active_flags returns list of flag names that are True."""
        risk = RiskClassification(assumption_mutation=True, coverage_gap=True)
        active = risk.active_flags()
        assert "assumption_mutation" in active
        assert "coverage_gap" in active
        assert "policy_divergence" not in active
        assert len(active) == 2


class TestCanonicalEvent:
    def test_create_minimal_event(self):
        """Can create event with required fields only."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="agent-1",
            action="fetch_data",
        )
        assert event.parent_event_id is None
        assert event.inputs == {}
        assert event.outputs == {}
        assert event.metadata == {}
        assert event.risk_classification is None

    def test_create_full_event(self):
        """Can create event with all fields."""
        parent_id = uuid4()
        event_id = uuid4()
        now = datetime.now(timezone.utc)

        event = CanonicalEvent(
            id=event_id,
            session_id="session-123",
            timestamp=now,
            event_type=EventType.BRANCH,
            agent_id="agent-1",
            parent_event_id=parent_id,
            action="decide_path",
            inputs={"options": ["a", "b"]},
            outputs={"chosen": "a"},
            metadata={"source": "test"},
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        assert event.id == event_id
        assert event.parent_event_id == parent_id
        assert event.inputs == {"options": ["a", "b"]}
        assert event.risk_classification.assumption_mutation is True

    def test_event_has_risk_flags(self):
        """has_risk_flags delegates to risk_classification."""
        event_no_risk = CanonicalEvent(
            id=uuid4(),
            session_id="s",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.OUTPUT,
            agent_id="a",
            action="x",
        )
        assert event_no_risk.has_risk_flags() is False

        event_with_risk = CanonicalEvent(
            id=uuid4(),
            session_id="s",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.OUTPUT,
            agent_id="a",
            action="x",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        assert event_with_risk.has_risk_flags() is True

    def test_event_exports_phase_2b_normalized_shape(self):
        event = CanonicalEvent(
            id=uuid4(),
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="agent-1",
            action="read_file",
            inputs={"file_path": "README.md"},
            outputs={"result": {"content": "# DriftShield"}},
            metadata={"tool_use_id": "tool-1"},
        )

        normalize_events([event], source_type="claude_code")
        payload = event.to_normalized_dict()

        assert payload["event_kind"] == "tool_call"
        assert payload["ordinal"] == 0
        assert payload["actor"] == {"id": "agent-1", "role": "assistant"}
        assert payload["summary"] == "read_file completed on README.md"
        assert payload["parent_event_refs"] == []
        assert payload["source_refs"] == [
            {"kind": "parser", "value": "claude_code"},
            {"kind": "tool_use_id", "value": "tool-1"},
        ]
        assert payload["artifact_refs"] == [
            {"kind": "file_path", "value": "README.md", "source": "inputs"},
        ]
        assert payload["tool_activity"] == {
            "name": "read_file",
            "category": None,
            "raw_name": "read_file",
            "status": "completed",
            "input_keys": ["file_path"],
            "has_outputs": True,
        }
        assert payload["ambiguities"] == []

    def test_event_preserves_list_based_constraints(self):
        event = CanonicalEvent(
            id=uuid4(),
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="agent-1",
            action="plan",
            inputs={
                "requirements": [
                    "Ask for confirmation before deleting files.",
                    "Stay within the repository root.",
                ]
            },
        )

        normalize_events([event], source_type="claude_code")

        assert {"kind": "requirements", "value": "Ask for confirmation before deleting files.", "source": "inputs"} in event.constraints
        assert {"kind": "requirements", "value": "Stay within the repository root.", "source": "inputs"} in event.constraints

    def test_event_handles_non_mapping_tool_inputs_in_normalization(self):
        event = CanonicalEvent(
            id=uuid4(),
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="agent-1",
            action="shell",
            inputs=["npm", "test"],
        )

        normalize_events([event], source_type="claude_code")

        assert event.tool_activity == {
            "name": "shell",
            "category": None,
            "raw_name": "shell",
            "status": "pending",
            "input_keys": [],
            "has_outputs": False,
        }


class TestSessionStatus:
    def test_status_values(self):
        """Session status enum has expected values."""
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.FAILED.value == "failed"


class TestSession:
    def test_create_session(self):
        """Can create a session with required fields."""
        session_id = uuid4()
        now = datetime.now(timezone.utc)

        session = Session(
            id=session_id,
            agent_id="doc-reviewer",
            started_at=now,
        )
        assert session.id == session_id
        assert session.external_id is None
        assert session.status == SessionStatus.RUNNING
        assert session.ended_at is None
        assert session.metadata == {}

    def test_create_completed_session(self):
        """Can create a completed session."""
        now = datetime.now(timezone.utc)

        session = Session(
            id=uuid4(),
            agent_id="doc-reviewer",
            started_at=now,
            ended_at=now,
            status=SessionStatus.COMPLETED,
            external_id="ext-123",
            metadata={"source": "langsmith"},
        )
        assert session.status == SessionStatus.COMPLETED
        assert session.external_id == "ext-123"
