"""Synthetic validation scenarios for testing DriftShield analysis."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import LineageGraph


def _ts(minutes: int) -> datetime:
    """Create timestamp offset from a base time."""
    base = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes)


def coverage_gap_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Agent reviews complex document, misses material exception.

    Contract review agent processes indemnification clause with 4 subsections.
    Subsection (c) contains "except where" carve-out.
    Agent summarizes as "standard structure" without referencing (c).

    Expected inflection: Node 4 (review_indemnity)
    Expected flags: coverage_gap, assumption_mutation
    """
    session_id = "coverage-gap-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="receive_document",
            inputs={"document_type": "MSA", "vendor": "DataFlow Inc"},
            outputs={"status": "received", "pages": 24},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="extract_clauses",
            parent_event_id=node1_id,
            inputs={"document_id": str(node1_id)},
            outputs={
                "clauses": {
                    "liability_cap": "12 months of fees",
                    "termination": "90 days notice",
                    "data_handling": "Processor role",
                    "indemnification": {
                        "full_text": "Supplier shall indemnify...(a)...(b)...(c) except where claim arises from Customer-provided data...(d)...",
                        "subsections": ["a", "b", "c", "d"],
                        "token_count": 847,
                    },
                }
            },
        )
    )
    node2_id = events[1].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.BRANCH,
            agent_id="doc-reviewer",
            action="review_liability",
            parent_event_id=node2_id,
            inputs={"clause": "liability_cap", "text": "12 months of fees"},
            outputs={"assessment": "Adequate for SaaS", "flag": False},
        )
    )
    node3_id = events[2].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.BRANCH,
            agent_id="doc-reviewer",
            action="review_indemnity",
            parent_event_id=node3_id,
            inputs={
                "clause": "indemnification",
                "full_text": "Supplier shall indemnify...(a)...(b)...(c) except where claim arises from Customer-provided data...(d)...",
                "subsections": ["a", "b", "c", "d"],
            },
            outputs={
                "assessment": "Standard indemnification structure",
                "referenced_subsections": ["a", "b", "d"],  # Missing (c)!
                "flag": False,
            },
            # This should be detected by analysis
            risk_classification=RiskClassification(
                coverage_gap=True,
                assumption_mutation=True,
            ),
        )
    )
    node4_id = events[3].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(4),
            event_type=EventType.TOOL_CALL,
            agent_id="doc-reviewer",
            action="generate_summary",
            parent_event_id=node4_id,
            inputs={"assessments": ["liability", "termination", "data", "indemnity"]},
            outputs={"summary": "No material risks identified"},
        )
    )
    node5_id = events[4].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(5),
            event_type=EventType.OUTPUT,
            agent_id="doc-reviewer",
            action="output",
            parent_event_id=node5_id,
            inputs={},
            outputs={
                "recommendation": "Proceed to signature",
                "flags": [],
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "coverage_gap",
        "description": "Agent misses material exception in complex clause",
        "expected_inflection_node_action": "review_indemnity",
        "expected_inflection_node_id": node4_id,
        "expected_risk_flags": ["coverage_gap", "assumption_mutation"],
        "failure_mode": "coverage_gap",
    }

    return graph, metadata


def assumption_introduction_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Agent makes inference not supported by inputs.

    Research agent retrieves sector data showing 4pt margin decline.
    Client data shows 6pt decline.
    Agent concludes "industry trend explains client decline" without
    computing relative underperformance.

    Expected inflection: Node 4 (reasoning_step)
    Expected flags: assumption_mutation
    """
    session_id = "assumption-intro-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="receive_application",
            inputs={"applicant": "MidWest Manufacturing", "request": "$2M credit line"},
            outputs={"status": "received"},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="fetch_financials",
            parent_event_id=node1_id,
            inputs={"company": "MidWest Manufacturing"},
            outputs={
                "revenue_trend": [12_000_000, 14_000_000, 11_000_000],
                "margin_trend": [0.18, 0.16, 0.12],  # 6pt decline
                "debt_ebitda": 2.9,
            },
        )
    )
    node2_id = events[1].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.TOOL_CALL,
            agent_id="underwriting-agent",
            action="fetch_industry_data",
            parent_event_id=node2_id,
            inputs={"sector": "manufacturing"},
            outputs={
                "sector_outlook": "Headwinds from supply chain normalization",
                "avg_margin_decline": 0.04,  # 4pt decline
            },
        )
    )
    node3_id = events[2].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.BRANCH,
            agent_id="underwriting-agent",
            action="reasoning_step",
            parent_event_id=node3_id,
            inputs={
                "client_margin_decline": 0.06,
                "sector_margin_decline": 0.04,
            },
            outputs={
                "reasoning": "Margin decline is industry-wide trend",
                "relative_comparison": None,  # Should have computed this!
            },
            risk_classification=RiskClassification(assumption_mutation=True),
        )
    )
    node4_id = events[3].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(4),
            event_type=EventType.OUTPUT,
            agent_id="underwriting-agent",
            action="output",
            parent_event_id=node4_id,
            inputs={},
            outputs={
                "recommendation": "APPROVE",
                "risk_rating": "Standard",
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "assumption_introduction",
        "description": "Agent uses sector data to excuse rather than benchmark client performance",
        "expected_inflection_node_action": "reasoning_step",
        "expected_inflection_node_id": node4_id,
        "expected_risk_flags": ["assumption_mutation"],
        "failure_mode": "assumption_mutation",
    }

    return graph, metadata


def cross_tool_contamination_scenario() -> tuple[LineageGraph, dict]:
    """
    Scenario: Output from Tool A incorrectly influences Tool B usage.

    Agent fetches customer data, then fetches pricing data.
    Customer metadata (discount tier) incorrectly applied to
    a different product's pricing calculation.

    Expected inflection: Node 3 (apply_pricing)
    Expected flags: context_contamination
    """
    session_id = "contamination-001"

    events = [
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(0),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="receive_order",
            inputs={"customer_id": "C123", "product_id": "P456"},
            outputs={"status": "received"},
        ),
    ]
    node1_id = events[0].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(1),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="fetch_customer",
            parent_event_id=node1_id,
            inputs={"customer_id": "C123"},
            outputs={
                "customer_name": "Acme Corp",
                "discount_tier": "gold",  # For product category A
                "discount_category": "A",
            },
        )
    )
    node2_id = events[1].id

    # THE INFLECTION NODE
    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(2),
            event_type=EventType.TOOL_CALL,
            agent_id="order-agent",
            action="apply_pricing",
            parent_event_id=node2_id,
            inputs={
                "product_id": "P456",
                "product_category": "B",  # Different category!
                "customer_discount_tier": "gold",  # From category A
            },
            outputs={
                "base_price": 100,
                "discount_applied": 0.20,  # Wrong! Gold tier doesn't apply to category B
                "final_price": 80,
            },
            risk_classification=RiskClassification(context_contamination=True),
        )
    )
    node3_id = events[2].id

    events.append(
        CanonicalEvent(
            id=uuid4(),
            session_id=session_id,
            timestamp=_ts(3),
            event_type=EventType.OUTPUT,
            agent_id="order-agent",
            action="output",
            parent_event_id=node3_id,
            inputs={},
            outputs={
                "order_total": 80,
                "status": "created",
            },
        )
    )

    graph = build_graph(events, session_id=session_id)

    metadata = {
        "name": "cross_tool_contamination",
        "description": "Discount from one category incorrectly applied to different category",
        "expected_inflection_node_action": "apply_pricing",
        "expected_inflection_node_id": node3_id,
        "expected_risk_flags": ["context_contamination"],
        "failure_mode": "context_contamination",
    }

    return graph, metadata


ALL_SCENARIOS = [
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
]
