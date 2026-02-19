"""Validate synthetic scenarios have expected structure."""

import pytest

from tests.fixtures.scenarios import (
    ALL_SCENARIOS,
    coverage_gap_scenario,
    assumption_introduction_scenario,
    cross_tool_contamination_scenario,
)


class TestScenarioStructure:
    """Verify all scenarios have correct structure for testing."""

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_returns_graph_and_metadata(self, scenario_fn):
        """Each scenario returns (graph, metadata) tuple."""
        result = scenario_fn()
        assert isinstance(result, tuple)
        assert len(result) == 2

        graph, metadata = result
        assert graph is not None
        assert isinstance(metadata, dict)

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_metadata_has_required_keys(self, scenario_fn):
        """Each scenario metadata has required keys."""
        _, metadata = scenario_fn()

        required_keys = [
            "name",
            "description",
            "expected_inflection_node_action",
            "expected_inflection_node_id",
            "expected_risk_flags",
            "failure_mode",
        ]
        for key in required_keys:
            assert key in metadata, f"Missing key: {key}"

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_graph_has_nodes(self, scenario_fn):
        """Each scenario graph has at least 2 nodes."""
        graph, _ = scenario_fn()
        assert len(graph.nodes) >= 2

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_inflection_node_exists(self, scenario_fn):
        """Expected inflection node exists in graph."""
        graph, metadata = scenario_fn()
        inflection_id = metadata["expected_inflection_node_id"]
        node = graph.get_node(inflection_id)

        assert node is not None
        assert node.action == metadata["expected_inflection_node_action"]

    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS)
    def test_scenario_inflection_node_has_risk_flags(self, scenario_fn):
        """Expected inflection node has risk flags set."""
        graph, metadata = scenario_fn()
        inflection_id = metadata["expected_inflection_node_id"]
        node = graph.get_node(inflection_id)

        assert node.has_risk_flags()

        # Check expected flags are set
        risk = node.event.risk_classification
        for flag in metadata["expected_risk_flags"]:
            assert getattr(risk, flag) is True, f"Expected flag {flag} to be True"


class TestCoverageGapScenario:
    """Specific tests for coverage gap scenario."""

    def test_has_four_subsections_in_input(self):
        """Inflection node input has 4 subsections."""
        graph, metadata = coverage_gap_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert "subsections" in node.inputs
        assert len(node.inputs["subsections"]) == 4

    def test_output_missing_subsection_c(self):
        """Inflection node output only references 3 subsections."""
        graph, metadata = coverage_gap_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        referenced = node.outputs.get("referenced_subsections", [])
        assert "c" not in referenced
        assert len(referenced) == 3


class TestAssumptionIntroductionScenario:
    """Specific tests for assumption introduction scenario."""

    def test_has_both_decline_values(self):
        """Inflection node has both client and sector decline in inputs."""
        graph, metadata = assumption_introduction_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert "client_margin_decline" in node.inputs
        assert "sector_margin_decline" in node.inputs
        assert node.inputs["client_margin_decline"] > node.inputs["sector_margin_decline"]

    def test_no_relative_comparison_computed(self):
        """Agent didn't compute relative comparison."""
        graph, metadata = assumption_introduction_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        assert node.outputs.get("relative_comparison") is None


class TestCrossToolContaminationScenario:
    """Specific tests for cross-tool contamination scenario."""

    def test_discount_category_mismatch(self):
        """Discount from category A applied to category B product."""
        graph, metadata = cross_tool_contamination_scenario()
        node = graph.get_node(metadata["expected_inflection_node_id"])

        # Product is category B but discount is from category A context
        assert node.inputs["product_category"] == "B"
        assert node.inputs["customer_discount_tier"] == "gold"
