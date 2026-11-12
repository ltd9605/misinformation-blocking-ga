"""Policy, work budgeting and descriptive diagnostic checks for pilot validation."""

from copy import deepcopy
import json
from math import sqrt
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from experiments.pilot_protocol_validation import collect_outputs, execute_case, load_settings
from src.data.specs import PROJECT_ROOT
from src.experiments import ExperimentConfig
from src.experiments.protocol import fixed_rumor_scenario, plan_methods, precision_diagnostics, projected_runtime, spread_diagnostics
from tests.experiment_helpers import experiment_values, processed_fixture
from tests.helpers import TemporaryFilesTest


class PilotPolicyTests(TemporaryFilesTest):
    def setUp(self):
        super().setUp()
        self.graph = processed_fixture(self.root)
        self.values = experiment_values(self.root, all_methods=True)

    def test_rumor_sampling_replays_with_sparse_actual_ids_and_graph_order(self):
        before = deepcopy(self.graph)
        scenario = fixed_rumor_scenario(self.graph, "fixture", 2026, 1)
        reverse = nx.DiGraph()
        reverse.add_nodes_from(reversed(list(self.graph)))
        reverse.add_edges_from(reversed(list(self.graph.edges)))
        self.assertEqual(scenario, fixed_rumor_scenario(reverse, "fixture", 2026, 1))
        self.assertEqual(len(scenario["rumor_seeds"]), 1)
        self.assertTrue(set(scenario["rumor_seeds"]) <= set(self.graph))
        self.assertTrue(nx.utils.graphs_equal(self.graph, before))

    def test_rumor_sampler_has_no_optimizer_or_diffusion_dependency(self):
        with patch("src.experiments.runner.evaluate_cic", side_effect=AssertionError("must not evaluate")):
            scenario = fixed_rumor_scenario(self.graph, "fixture", 0, 2)
        self.assertEqual(len(scenario["rumor_seeds"]), 2)
        self.assertEqual(scenario["scope"], "fixed_across_p_methods_and_independent_algorithm_runs")

    def test_reachability_respects_directed_edges_and_isolates(self):
        graph = nx.DiGraph([(100, 500)])
        graph.add_node(900)
        scenario = fixed_rumor_scenario(graph, "fixture", 10, 3)
        self.assertEqual(scenario["reachable_node_count"], 3)
        self.assertEqual(scenario["seed_degrees"], {"100": 1, "500": 0, "900": 0})

    def test_invalid_rumor_count_fails(self):
        for count in (-1, True, len(self.graph) + 1):
            with self.subTest(count=count), self.assertRaises(ValueError):
                fixed_rumor_scenario(self.graph, "fixture", 0, count)

    def test_full_greedy_skip_is_explicit_and_never_renames_restricted(self):
        self.values["limits"]["max_full_greedy_evaluations"] = 4
        with patch("src.experiments.runner.evaluate_cic", side_effect=AssertionError("preflight only")):
            config, estimates = plan_methods(self.graph, self.values)
        c = config.to_dict()
        self.assertNotIn("full_greedy", c["algorithms"])
        self.assertIn("candidate_restricted_greedy", c["algorithms"])
        self.assertIn("Full Greedy blocked", c["skipped_algorithms"]["full_greedy"])
        full = next(row for row in estimates if row["algorithm"] == "full_greedy")
        self.assertEqual(full["optimization_evaluation_upper_bound"], 5)
        self.assertEqual(full["optimization_cic_simulation_upper_bound"], 10)
        self.assertEqual(full["final_cic_simulations"], 0)
        self.assertEqual(full["status"], "skipped")

    def test_full_greedy_can_run_when_budget_permits(self):
        config, estimates = plan_methods(self.graph, self.values)
        self.assertIn("full_greedy", config.to_dict()["algorithms"])
        self.assertFalse(config.to_dict()["skipped_algorithms"])
        self.assertEqual(len(estimates), 7)
        self.assertTrue(all(row["status"] == "planned" for row in estimates))

    def test_invalid_candidate_pool_is_error_not_silently_skipped(self):
        self.values["candidate_restriction"] = {"method": "explicit", "nodes": [10, 20]}
        with self.assertRaisesRegex(ValueError, "rumor nodes"):
            plan_methods(self.graph, self.values)

    def test_smoke_projection_is_distinct_from_measured_runtime(self):
        smoke = {"results": [{"optimization_evaluator_seconds": 1, "optimization_cic_simulations": 10,
                              "final_evaluation_runtime_seconds": 2, "final_cic_simulations": 10}],
                 "timings": {"total_experiment_runtime_seconds": 4}}
        costs = [{"status": "planned", "optimization_cic_simulation_upper_bound": 50, "final_cic_simulations": 10},
                 {"status": "skipped", "optimization_cic_simulation_upper_bound": 9999, "final_cic_simulations": 0}]
        self.assertEqual(projected_runtime(smoke, costs, 2), 32)
        with self.assertRaises(ValueError):
            projected_runtime(smoke, costs, 0.5)

    def test_protocol_configuration_keeps_proposed_parameters(self):
        path = PROJECT_ROOT / "experiments/configs/pilot_protocol_validation.json"
        settings = load_settings(path)
        self.assertEqual((settings["k"], settings["S_opt"], settings["S_eval"], settings["independent_runs"]), (5, 20, 200, 3))
        self.assertEqual(settings["propagation_probabilities"], [0.01, 0.05])
        self.assertEqual(settings["ga_parameters"]["population_size"], 10)
        self.assertEqual(settings["ga_parameters"]["max_generations"], 10)

    def test_invalid_protocol_limits_and_missing_keys_fail(self):
        original = json.loads((PROJECT_ROOT / "experiments/configs/pilot_protocol_validation.json").read_text())
        for changes in ({"independent_runs": 0}, {"datasets": ["not-a-dataset"]},
                        {"propagation_probabilities": [0.05, 0.05]}, {"save_raw_observations": False},
                        {"resources": {"max_total_wall_seconds": 2}}):
            path = self.write(json.dumps({**original, **changes}), "bad.json")
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                load_settings(path)

    def test_timeout_does_not_claim_partial_work_was_zero(self):
        import subprocess
        config = ExperimentConfig.from_dict(self.values)
        with patch("experiments.pilot_protocol_validation.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 1)):
            result = execute_case(config, self.root / "case.json", 1, self.root)
        self.assertEqual(result["status"], "timed_out")
        self.assertIsNone(result["run_directory"])
        self.assertIn("partial CIC work unknown", result["reason"])


class PilotDiagnosticTests(TemporaryFilesTest):
    def test_low_spread_and_global_saturation_are_distinct(self):
        low = spread_diagnostics([1, 1, 2], node_count=1000, rumor_count=1, reachable_count=2,
                                 low_fraction=0.01, saturation_fraction=0.9)
        self.assertTrue(low["low_spread"])
        self.assertFalse(low["near_graph_saturation"])
        self.assertEqual(low["no_spread_fraction"], 2 / 3)
        saturated = spread_diagnostics([95, 99], node_count=100, rumor_count=1, reachable_count=100,
                                       low_fraction=0.01, saturation_fraction=0.9)
        self.assertTrue(saturated["near_graph_saturation"])
        self.assertEqual(saturated["near_saturation_observation_fraction"], 1)

    def test_pooled_control_standard_error_is_correct(self):
        metrics = spread_diagnostics([1, 2, 3, 4], node_count=10, rumor_count=1, reachable_count=10,
                                     low_fraction=0.01, saturation_fraction=0.9)
        self.assertEqual(metrics["control_rumor_mean"], 2.5)
        self.assertAlmostEqual(metrics["standard_error"], sqrt(5 / 3) / 2)

    def test_nested_prefix_precision_and_required_S_are_estimates(self):
        rows = precision_diagnostics([1, 2, 3, 4], 10, [2, 4, 8], 0.1, 0.05)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["difference_from_full_heldout_mean"], -1)
        self.assertEqual(rows[1]["difference_from_full_heldout_mean"], 0)
        self.assertEqual(rows[1]["required_S_opt_plugin"], 2)
        self.assertEqual(rows[1]["required_S_eval_plugin"], 7)

    def test_single_observation_precision_stays_undefined(self):
        row = precision_diagnostics([1], 100, [1], 0.01, 0.005)[0]
        self.assertIsNone(row["standard_error"])
        self.assertIsNone(row["required_S_opt_plugin"])

    def test_invalid_diagnostic_input_is_rejected(self):
        with self.assertRaises(ValueError):
            spread_diagnostics([], node_count=10, rumor_count=1, reachable_count=10, low_fraction=0.01, saturation_fraction=0.9)
        with self.assertRaises(ValueError):
            precision_diagnostics([1], 10, [0], 0.01, 0.005)

    def test_skipped_comparison_has_statuses_without_fabricated_metrics(self):
        cases = [{"case_id": "test", "phase": "pilot", "dataset": "toy", "p": 0.05, "replicate_index": 0,
                  "independent_run_index": 0, "status": "skipped", "reason": "budget exhausted",
                  "preflight": [{"algorithm": "genetic_algorithm", "status": "planned", "reason": None}]}]
        summary = collect_outputs(self.root, cases, {}, {"purpose": "unit-test"})
        self.assertEqual(summary["successful_method_rows"], 0)
        self.assertEqual(summary["skipped_method_rows"], 1)
        self.assertEqual(summary["measured_completed_cic_simulations"], 0)
        self.assertEqual((self.root / "results.csv").read_text(), "")
