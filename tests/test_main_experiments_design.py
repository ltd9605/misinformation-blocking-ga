"""Design-only admission, frozen inputs, honest runtime proxies and no main calls."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.design_main_experiments import (
    METHODS, build_plan, export_plan, grouped_preflight, method_costs, validate_request, write_report,
)
from src.data.specs import PROJECT_ROOT
from src.experiments.config import ExperimentConfig, ExperimentConfigError


class MainDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((PROJECT_ROOT/"experiments/configs/main_experiments_protocol.json").read_text())
        cls.plan = build_plan(cls.request)

    def test_user_locked_GA_and_research_conditions_preserved(self):
        p, q = self.plan["base_protocol"], self.request
        self.assertEqual(q["GA"], p["reference_ga"])
        for key in ("k", "p", "S_opt", "S_eval_per_batch", "tie_breaking", "final_batches"):
            self.assertEqual(q[key], p[key])
        self.assertFalse(q["execution_authorized"])
        self.assertFalse(q["design_confirmed"])

    def test_invalid_locked_GA_or_probability_rejected(self):
        for change in ({"GA": {**self.request["GA"], "population_size": 20}}, {"p": .05}, {"S_opt": 20}):
            with self.assertRaises(ValueError):
                validate_request({**self.request, **change})

    def test_budget_and_execution_cannot_be_silently_raised(self):
        for change in ({"execution_authorized": True}, {"design_confirmed": True},
                       {"admission_budget": {**self.request["admission_budget"], "max_projected_seconds": 12000}}):
            with self.assertRaises(ValueError):
                validate_request({**self.request, **change})

    def test_all_reserved_scenarios_and_previous_sampling_retained(self):
        s = self.plan["scenarios"]
        self.assertEqual([x["rumor_seeds"] for x in s], [[485], [374], [714], [2733], [1961], [1795]])
        self.assertTrue(all(not r["prior_R_overlap"] and r["main_MC_observations_generated"] == 0 for r in s))
        self.assertTrue(all(not set(r["rumor_seeds"]) & set(r["known_prior_R_ids"]) for r in s))
        self.assertEqual([r["reachable_count"] for r in s], [965, 965, 4039, 4039, 2316, 2317])

    def test_low_growth_main_case_is_analytic_and_not_dropped(self):
        s = next(r for r in self.plan["scenarios"] if r["rumor_seeds"] == [1961])
        self.assertEqual(s["propagation_degree"], 5)
        self.assertAlmostEqual(s["no_intervention_no_growth_probability_analytic"], .97**5)
        self.assertIsNone(s["measured_rumor_mean"])
        self.assertEqual(len(self.plan["supplementary_scenarios_retained"]), 5)

    def test_matrix_all_scenarios_methods_and_five_repetitions(self):
        rows = self.plan["matrix"]
        self.assertEqual(len(rows), 210)
        self.assertEqual(sum(r["method_eligible"] for r in rows), 180)
        self.assertEqual(len({r["unit_id"] for r in rows}), 210)
        for s in self.plan["scenarios"]:
            for method in (*METHODS, "full_greedy"):
                self.assertEqual({r["repetition_index"] for r in rows if r["scenario_id"] == s["scenario_id"] and r["algorithm"] == method}, set(range(5)))

    def test_all_six_methods_have_identical_scientific_and_final_seed_conditions(self):
        for scenario in self.plan["scenarios"]:
            for repeat in range(5):
                rows = [r for r in self.plan["matrix"] if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat]
                for key in ("rumor_seeds", "k", "p", "tie_breaking", "S_opt", "S_eval_per_batch", "final_batches", "final_batch_seeds"):
                    self.assertTrue(all(r[key] == rows[0][key] for r in rows))
                self.assertEqual(next(r for r in rows if r["algorithm"] == "no_intervention")["actual_P_size"], 0)

    def test_seed_plan_matches_reserved_main_slots_and_remains_disjoint(self):
        slots = json.loads((PROJECT_ROOT/self.request["seed_reservation"]).read_text())
        by_slot = {(r["scenario_id"], r["repetition_index"]): r for r in slots}
        ga_rows = [r for r in self.plan["matrix"] if r["algorithm"] == "genetic_algorithm"]
        self.assertEqual(len({r["GA_random_seed"] for r in ga_rows}), 30)
        for row in ga_rows:
            slot = by_slot[(row["scenario_id"], row["repetition_index"])]
            self.assertEqual(row["final_batch_seeds"], slot["final_batch_seeds"])
            self.assertEqual(row["optimization_base_random_seed"], slot["optimization_base_random_seed"])
            for other in ga_rows:
                self.assertTrue(row["optimization_seed_stop_exclusive"] <= other["final_batch_seeds"][0] or
                                other["final_seed_stop_exclusive"] <= row["optimization_base_random_seed"])

    def test_exact_evaluator_and_CIC_upper_bounds_include_all_batches(self):
        p = self.plan["preflight"]
        self.assertEqual((p["GA_runs"], p["optimization_evaluator_calls_upper"], p["final_evaluator_calls"]), (30, 4200, 360))
        self.assertEqual((p["total_evaluator_calls_upper"], p["optimization_CIC_upper"], p["final_CIC"], p["total_CIC_upper"]), (4560, 420000, 1320000, 1740000))
        self.assertEqual(sum(r["budgeted_optimization_CIC_upper"]+r["budgeted_final_CIC"] for r in self.plan["matrix"]), p["total_CIC_upper"])
        self.assertEqual(sum(r["budgeted_final_evaluator_calls"] for r in self.plan["matrix"] if r["algorithm"] == "no_intervention"), 60)

    def test_five_repeats_blocked_without_automatically_selecting_smaller_design(self):
        p = self.plan["preflight"]
        self.assertFalse(p["within_declared_budget"])
        self.assertGreater(p["projected_seconds_including_safety_and_overhead"], 10800)
        self.assertLess(p["runtime_headroom_seconds"], 0)
        self.assertEqual(self.request["proposed_independent_runs"], 5)
        self.assertFalse(self.plan["automatic_repeat_change"])
        self.assertTrue(all(not a["selected"] and a["requires_user_confirmation"] for a in self.plan["alternatives"]))
        for row in self.plan["matrix"]:
            if row["method_eligible"]:
                self.assertEqual(row["admission_status"], "blocked_global_preflight")

    def test_full_greedy_skipped_with_its_exact_cost_and_specific_reason(self):
        for dataset, nodes, expected in (("email-Eu-core", 1005, 5010), ("ego-Facebook", 4039, 20180), ("Wiki-Vote", 7115, 35560)):
            cost = method_costs(self.request, nodes)["full_greedy"]
            self.assertEqual(cost["optimization_evaluator_calls_upper"], expected)
            self.assertFalse(cost["method_eligible"])
            self.assertIn(str(expected), cost["method_skip_reason"])
            rows = [r for r in self.plan["matrix"] if r["dataset"] == dataset and r["algorithm"] == "full_greedy"]
            self.assertEqual(len(rows), 10)
            self.assertTrue(all(r["budgeted_optimization_CIC_upper"] == 0 and r["admission_status"] == "skipped_method_cost_limits" for r in rows))

    def test_per_dataset_and_scenario_costs_reconcile(self):
        p = self.plan["preflight"]
        for key in ("scenario_id", "dataset"):
            rows = grouped_preflight(self.plan, key)
            self.assertEqual(sum(r["optimization_CIC_upper"]+r["final_CIC"] for r in rows), p["total_CIC_upper"])
            self.assertAlmostEqual(sum(r["proxy_max_seconds_before_safety"] for r in rows), p["runtime_proxy_max_seconds_before_safety"])

    def test_runtime_sources_are_measured_related_context_not_main_measurements(self):
        records = self.plan["runtime_records"]
        main_R = {(r["dataset"], r["rumor_seeds"][0]) for r in self.plan["scenarios"]}
        self.assertTrue(all((r["dataset"], r["rumor_seeds"][0]) not in main_R and r["p"] == .03 for r in records))
        for row in self.plan["preflight"]["rows"]:
            self.assertIsNone(row["observed_main_R_runtime_seconds"])
            self.assertIsNone(row["main_R_point_estimate_seconds"])
            self.assertFalse(row["scenario_runtime_identity_assumed"])
            self.assertGreaterEqual(row["proxy_max_seconds_before_safety"], row["proxy_min_seconds_before_safety"])
        wiki = [r for r in grouped_preflight(self.plan, "scenario_id") if r["dataset"] == "Wiki-Vote"]
        self.assertNotEqual(wiki[0]["nearest_topology_nominal_proxy_seconds"], wiki[1]["nearest_topology_nominal_proxy_seconds"])

    def test_rate_provenance_can_be_recomputed_from_source_row(self):
        record = next(r for r in self.plan["runtime_records"] if r["source"].endswith("accuracy_statistics.json"))
        row = json.loads((PROJECT_ROOT/record["source"]).read_text())[record["source_row_index"]]
        self.assertEqual(record["measured_units"], 2500)
        self.assertAlmostEqual(record["seconds_per_unit"], row["runtime_prefix_MC_seconds"]/row["S_eval"])

    def test_statistics_prespecify_family_weights_and_no_equivalence_claim(self):
        p = self.request["analysis_policy"]
        self.assertEqual(p["primary_CI_family_size"], 45)
        self.assertEqual(p["scenario_effects"], 6*5)
        self.assertEqual(p["within_dataset_equal_scenario_weight_effects"], 3*5)
        self.assertEqual(p["within_dataset_scenario_weights"], [.5, .5])
        self.assertIsNone(p["practical_equivalence_margin"])
        self.assertFalse(p["cross_dataset_effect_pooling"])
        self.assertFalse(p["scenario_population_inference"])

    def test_planning_calls_no_diffusion_evaluator_or_optimizer(self):
        with patch("src.evaluation.monte_carlo.simulate_cic", side_effect=AssertionError("MC forbidden")) as mc, \
             patch("src.algorithms.genetic_algorithm.evaluate_cic", side_effect=AssertionError("fitness forbidden")) as ga, \
             patch("src.algorithms.greedy.evaluate_cic", side_effect=AssertionError("greedy forbidden")) as greedy:
            p = build_plan(self.request)
            self.assertEqual(p["official_main_CIC_simulations"], 0)
            mc.assert_not_called(); ga.assert_not_called(); greedy.assert_not_called()

    def test_export_blocked_design_null_metrics_and_no_main_runner_schema(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"export"
            result = export_plan(self.plan, root)
            self.assertEqual(result["status"], "stopped_at_preflight")
            rows = json.loads((root/"matrix.json").read_text())
            self.assertEqual(len(rows), 210)
            self.assertTrue(all(r["actual_CIC_simulations"] == 0 and r["protector_seeds"] is None and r["measured_rumor_mean"] is None for r in rows))
            with self.assertRaises(FileExistsError):
                export_plan(self.plan, root)
            with self.assertRaises(ExperimentConfigError):
                ExperimentConfig.from_dict(json.loads((root/"config.json").read_text()))

    def test_report_uses_proposed_plan_and_preserves_unconfirmed_conditions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            export_plan(self.plan, root/"artifacts")
            write_report(self.plan, root/"report.md", root/"artifacts")
            report = (root/"report.md").read_text()
            self.assertIn("BLOCKED AT PREFLIGHT", report)
            self.assertIn("0 main evaluator calls", report)
            self.assertIn("CI family chứa0", report)
            self.assertIn("one-batch", report)
            self.assertEqual(len(self.plan["unconfirmed_conditions"]), 10)


if __name__ == "__main__":
    unittest.main()
