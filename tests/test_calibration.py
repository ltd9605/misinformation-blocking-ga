"""Exact topology oracles and independent checks of Pilot 2 statistics."""

from copy import deepcopy
from math import sqrt
from time import perf_counter
import unittest
from unittest.mock import patch

import networkx as nx

from src.experiments.calibration import (
    choose_representative, jaccard, observation_summary, paired_differences,
    ranking_diagnostics, reachable_sizes, reachability_summary, sample_reachable_scenarios,
)
from src.evaluation import evaluate_cic
from experiments.pilot_2_calibration import CalibrationStudy
from experiments.analyze_pilot_2 import order_agreement


class ReachabilityCalibrationTests(unittest.TestCase):
    def test_scc_bitsets_match_independent_descendant_oracle(self):
        graph = nx.DiGraph([(10, 20), (20, 10), (20, 30), (30, 40), (50, 30), (60, 50)])
        graph.add_node(99)
        expected = {v: len(nx.descendants(graph, v)) + 1 for v in graph}
        self.assertEqual(reachable_sizes(graph), expected)

    def test_disjoint_branches_and_shared_descendants_are_not_double_counted(self):
        graph = nx.DiGraph([(1, 2), (1, 3), (2, 4), (3, 4)])
        self.assertEqual(reachable_sizes(graph), {1: 4, 2: 2, 3: 2, 4: 1})

    def test_random_digraphs_match_per_source_BFS_oracle(self):
        for seed in range(20):
            graph = nx.gnp_random_graph(9, .2, seed=seed, directed=True)
            expected = {v: len(nx.descendants(graph, v))+1 for v in graph}
            with self.subTest(seed=seed):
                self.assertEqual(reachable_sizes(graph), expected)

    def test_undirected_components_include_isolates(self):
        graph = nx.Graph([(10, 20), (20, 30), (40, 50)])
        graph.add_node(99)
        self.assertEqual(reachable_sizes(graph), {10: 3, 20: 3, 30: 3, 40: 2, 50: 2, 99: 1})

    def test_sparse_huge_and_negative_ids_use_ordinals(self):
        graph = nx.DiGraph([(-10**12, 10**12), (10**12, 500)])
        self.assertEqual(reachable_sizes(graph), {-10**12: 3, 10**12: 2, 500: 1})

    def test_graph_attributes_and_topology_are_unchanged(self):
        graph = nx.DiGraph([(100, 200), (200, 100)])
        graph.nodes[100]["label"] = [1, 2]
        before = deepcopy(graph)
        reachable_sizes(graph)
        self.assertTrue(nx.utils.graphs_equal(graph, before))

    def test_multigraph_is_rejected(self):
        with self.assertRaises(TypeError):
            reachable_sizes(nx.MultiGraph())

    def test_distribution_counts_ties_and_linear_quantiles(self):
        summary = reachability_summary({10: 1, 20: 1, 30: 9, 40: 9})
        self.assertEqual(summary["histogram"], [{"reachable_count": 1, "source_node_count": 2}, {"reachable_count": 9, "source_node_count": 2}])
        self.assertEqual(summary["quantiles_linear"]["0.5"], 5)
        self.assertEqual(summary["mean"], 5)
        with self.assertRaises(ValueError):
            reachability_summary({})

    def test_empty_middle_stratum_is_not_fabricated(self):
        scenarios, strata = sample_reachable_scenarios({10: 1, 20: 2, 30: 99, 40: 100}, "fixture", 10)
        middle = next(s for s in strata if s["stratum"] == "medium")
        self.assertEqual(middle["candidate_count"], 0)
        self.assertEqual(middle["status"], "empty_topological_stratum")
        self.assertEqual({s["stratum"] for s in scenarios}, {"low", "high"})

    def test_homogeneous_graph_has_one_constant_stratum(self):
        scenarios, strata = sample_reachable_scenarios({10: 3, 30: 3, 90: 3}, "connected", 5)
        self.assertTrue(all(s["stratum"] == "constant" for s in scenarios))
        self.assertEqual(len(scenarios), 2)
        self.assertEqual(sum(s["candidate_count"] for s in strata), 3)

    def test_uniform_stratified_seed_selection_replays_without_id_assumptions(self):
        counts = {10: 1, 90: 2, 700: 3, 2000: 90, 9999: 100}
        first = sample_reachable_scenarios(counts, "sparse", 2026)
        second = sample_reachable_scenarios(dict(reversed(list(counts.items()))), "sparse", 2026)
        self.assertEqual(first, second)
        self.assertTrue(all(s["rumor_seeds"][0] in counts for s in first[0]))

    def test_low_reach_and_legacy_seeds_remain_supplementary(self):
        scenarios, _ = sample_reachable_scenarios({10: 1, 20: 2, 30: 100, 40: 99}, "fixture", 2026, per_stratum=1, legacy_seed=20)
        self.assertTrue(any(s["rumor_seeds"] == [20] for s in scenarios))
        self.assertTrue(any(s["role"] == "supplementary_low_reach" for s in scenarios))
        with self.assertRaises(ValueError):
            sample_reachable_scenarios({10: 1}, "fixture", 1, legacy_seed=99)


class CalibrationStatisticsTests(unittest.TestCase):
    def test_mean_population_std_sample_SE_and_t_interval(self):
        result = observation_summary([1, 2, 3, 4], 10, 10)
        self.assertEqual(result["rumor_mean"], 2.5)
        self.assertAlmostEqual(result["rumor_std_population"], sqrt(1.25))
        self.assertAlmostEqual(result["rumor_SE"], sqrt(5 / 3) / 2)
        self.assertAlmostEqual(result["ci95_half_width"], 3.182446305 * sqrt(5 / 3) / 2, places=6)

    def test_zero_observed_variance_does_not_establish_structural_certainty(self):
        result = observation_summary([1]*500, 100, 20)
        self.assertTrue(result["zero_variance_not_structurally_certain"])
        self.assertLess(result["no_spread_wilson95_low"], 1)
        self.assertEqual(result["no_spread_wilson95_high"], 1)
        self.assertFalse(observation_summary([1]*500, 100, 1)["zero_variance_not_structurally_certain"])

    def test_single_observation_has_no_mean_confidence_interval(self):
        result = observation_summary([1], 100, 1)
        self.assertIsNone(result["rumor_SE"])
        self.assertIsNone(result["ci95_low"])

    def test_paired_interval_uses_seed_aligned_differences(self):
        result = paired_differences([10, 20, 30, 40], [9, 19, 29, 39])
        self.assertEqual(result["mean_difference"], 1)
        self.assertEqual(result["SE_difference"], 0)
        self.assertFalse(result["unresolved_at_pointwise_95"])
        with self.assertRaises(ValueError):
            paired_differences([1], [1, 2])

    def test_ranking_preserves_exact_ties_and_reports_uncertainty(self):
        order, comparisons = ranking_diagnostics({"b": [1, 2, 3], "a": [1, 2, 3], "c": [3, 4, 5]})
        self.assertEqual(order, ["a", "b", "c"])
        tied = next(c for c in comparisons if c["first"] == "a" and c["second"] == "b")
        self.assertTrue(tied["unresolved_at_pointwise_95"])
        self.assertEqual(len(comparisons), 3)

    def test_protector_overlap(self):
        self.assertEqual(jaccard([1, 2], [2, 3]), 1 / 3)
        self.assertEqual(jaccard([], []), 1)

    def test_representative_gate_uses_only_control_and_manifest_policy(self):
        scenarios = [{"scenario_id": "low", "role": "supplementary_low_reach"},
                     {"scenario_id": "high0", "role": "primary_candidate"},
                     {"scenario_id": "high1", "role": "primary_candidate"}]
        rows = [{"scenario_id": "low", "p": .01, "rumor_fraction": .1, "reachable_fraction_activated": .5},
                {"scenario_id": "high0", "p": .05, "rumor_fraction": .3, "reachable_fraction_activated": .4},
                {"scenario_id": "high1", "p": .03, "rumor_fraction": .2, "reachable_fraction_activated": .6}]
        chosen = choose_representative(rows, scenarios, min_fraction=.02, max_fraction=.8, max_reachable_fraction=.9)
        self.assertEqual(chosen["scenario_id"], "high1")
        self.assertEqual(chosen["calibration_admission"], "informative_control_only")

    def test_saturation_is_excluded_from_calibration_gate_but_not_deleted(self):
        rows = [{"scenario_id": "x", "p": .05, "rumor_fraction": .95, "reachable_fraction_activated": .95}]
        chosen = choose_representative(rows, [{"scenario_id": "x", "role": "primary_candidate"}],
                                       min_fraction=.02, max_fraction=.8, max_reachable_fraction=.9)
        self.assertEqual(chosen["calibration_admission"], "fallback_no_cell_met_control_gate")
        self.assertEqual(rows[0]["rumor_fraction"], .95)

    def test_chunked_independent_evaluation_equals_single_core_call(self):
        graph = nx.DiGraph([(10, 20), (20, 30), (40, 30), (30, 50)])
        expected = evaluate_cic(graph, [10], [40], .4, 11, base_random_seed=200, tie_breaking="protector-priority")
        chunks, offset = [], 0
        for size in (3, 2, 6):
            result = evaluate_cic(graph, [10], [40], .4, size, base_random_seed=200+offset, tie_breaking="protector-priority")
            chunks.extend((v.random_seed, v.rumor_count, v.protector_count, v.inactive_count) for v in result.raw_results)
            offset += size
        self.assertEqual(chunks, [(v.random_seed, v.rumor_count, v.protector_count, v.inactive_count) for v in expected.raw_results])

    def test_ranking_order_flips_do_not_confuse_ties_with_label_order(self):
        metrics = order_agreement({"a": 1, "b": 2, "c": 2}, {"a": 2, "b": 1, "c": 2})
        self.assertEqual(metrics["strict_order_flips"], 1)
        self.assertEqual(metrics["tie_status_changes"], 2)
        self.assertEqual(metrics["pair_count"], 3)


class CalibrationBudgetTests(unittest.TestCase):
    def study(self):
        study = CalibrationStudy.__new__(CalibrationStudy)
        study.c = {"resources": {"max_cic_simulations": 100, "max_wall_seconds": 60}}
        study.budget = {"charged_cic_simulations": 80, "measured_cic_simulations": 80,
                        "phase_wall_seconds": {"earlier": 10}, "unknown_partial_work": False}
        study.phase_started = perf_counter()
        return study

    def test_admission_rejects_simulation_and_runtime_budgets_before_execution(self):
        study = self.study()
        self.assertEqual(study.admission(21), "simulation_budget_exceeded")
        self.assertEqual(study.admission(10, 60), "active_execution_wall_budget_exceeded")
        self.assertIsNone(study.admission(20, 1))

    def test_timeout_charge_preserves_unknown_actual_work(self):
        study = self.study()
        with patch.object(study, "save_budget"):
            study.charge(20, measured=False)
        self.assertEqual(study.budget["charged_cic_simulations"], 100)
        self.assertEqual(study.budget["measured_cic_simulations"], 80)
        self.assertTrue(study.budget["unknown_partial_work"])
