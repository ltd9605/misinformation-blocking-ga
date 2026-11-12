"""Budget stop, complete run matrix and strictly one-factor planned comparisons."""

from copy import deepcopy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.preflight_reduced_screen import export_plan, plan_reduced_screen, validate_ofat_pair
from src.data.specs import PROJECT_ROOT
from src.experiments.sensitivity import FACTORS, sensitivity_seed_plan


class ReducedScreenPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((PROJECT_ROOT/"experiments/configs/milestone_7_reduced_screen.json").read_text())
        cls.plan = plan_reduced_screen(cls.request)

    def test_nine_profiles_five_selected_and_reference_in_all_panels(self):
        self.assertEqual(len(self.plan["all_nine_profiles"]), 9)
        self.assertEqual(len(self.plan["selected_profiles"]), 5)
        ref = [r for r in self.plan["all_OFAT_panels"] if r["profile_id"] == "reference"]
        self.assertEqual({r["factor"] for r in ref}, set(FACTORS))
        self.assertEqual(len(ref), 4)

    def test_original_45_is_total_and_five_repeats_give_75(self):
        self.assertEqual(self.plan["original_three_repeat_preflight"]["GA_runs"], 45)
        self.assertEqual(len(self.plan["matrix"]), 75)
        for dataset in self.plan["base_protocol"]["datasets"]:
            self.assertEqual(sum(row["dataset"] == dataset for row in self.plan["matrix"]), 25)
        self.assertEqual(len({r["run_id"] for r in self.plan["matrix"]}), 75)

    def test_all_requested_run_fields_and_repetition_coverage_are_present(self):
        required = {"dataset", "rumor_seeds", "k", "p", "S_opt", "S_eval", "population_size", "max_generations",
                    "crossover_rate", "mutation_rate", "repetition_index", "GA_random_seed", "GA_operators_seed",
                    "optimization_base_random_seed", "final_batch_0_base_random_seed", "final_batch_1_base_random_seed"}
        for row in self.plan["matrix"]:
            self.assertTrue(required <= row.keys())
        for profile in self.plan["selected_profiles"]:
            for scenario in self.plan["development_scenarios"]:
                repetitions = {r["repetition_index"] for r in self.plan["matrix"] if r["profile_id"] == profile["profile_id"] and r["scenario_id"] == scenario["scenario_id"]}
                self.assertEqual(repetitions, set(range(5)))

    def test_exact_call_counts_and_time_budget_stop(self):
        p = self.plan["requested_preflight"]
        self.assertEqual((p["fitness_evaluator_calls_upper"], p["GA_final_evaluator_calls"], p["control_evaluator_calls"]), (10500, 150, 30))
        self.assertEqual((p["total_evaluator_calls_upper"], p["total_CIC_upper"]), (10680, 1710000))
        self.assertAlmostEqual(p["rate_projection_seconds_with_safety"], 10985.164150622337)
        self.assertFalse(p["within_declared_budget"])
        self.assertEqual(p["budget_reasons"], ["Pilot2_rate_projection_exceeds_budget"])
        self.assertFalse(p["runtime_is_measured"])

    def test_per_dataset_costs_reconcile_without_duplicate_controls(self):
        rows = self.plan["preflight_by_dataset"]
        self.assertEqual([r["total_CIC_upper"] for r in rows], [710000, 500000, 500000])
        self.assertEqual(sum(r["total_CIC_upper"] for r in rows), self.plan["requested_preflight"]["total_CIC_upper"])
        self.assertAlmostEqual(sum(r["rate_projection_seconds_with_safety"] for r in rows), self.plan["requested_preflight"]["rate_projection_seconds_with_safety"])

    def test_only_baseline_vs_single_factor_pairs_are_planned(self):
        rows = {r["run_id"]: r for r in self.plan["matrix"]}
        self.assertEqual(len(self.plan["pairs"]), 60)
        for pair in self.plan["pairs"]:
            validate_ofat_pair(rows[pair["reference_run_id"]], rows[pair["alternative_run_id"]], pair["factor"])
        reference = next(r for r in self.plan["matrix"] if r["profile_id"] == "reference")
        alternative = next(r for r in self.plan["matrix"] if r["profile_id"] == "population_size_20")
        for changes in ({"p": .05}, {"mutation_rate": .2}, {"repetition_index": 4}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_ofat_pair(reference, {**alternative, **changes}, "population_size")

    def test_optimization_final_and_future_main_seed_ranges_are_separate(self):
        main = deepcopy(self.plan["effective_protocol"])
        main["random_seed_policy"]["master_seed"] = self.request["reserved_main_master_seed"]
        seen = {}
        for row in self.plan["matrix"]:
            self.assertLessEqual(row["optimization_seed_stop_exclusive"], row["final_batch_0_base_random_seed"])
            self.assertLess(row["final_batch_0_base_random_seed"], row["final_batch_1_base_random_seed"])
            self.assertLessEqual(row["final_seed_stop_exclusive"], row["block_stop_exclusive"])
            reserved = sensitivity_seed_plan(main, row["scenario_index"], row["repetition_index"])
            self.assertTrue(row["block_stop_exclusive"] <= reserved["block_start"] or reserved["block_stop_exclusive"] <= row["block_start"])
            key = (row["scenario_id"], row["repetition_index"])
            current = (row["optimization_base_random_seed"], row["final_batch_0_base_random_seed"], row["GA_operators_seed"])
            if key in seen:
                self.assertEqual(current, seen[key])
            seen[key] = current
        intervals = sorted({(r["block_start"], r["block_stop_exclusive"]) for r in self.plan["matrix"]})
        self.assertEqual(len(intervals), 15)
        self.assertTrue(all(stop <= start2 for (_, stop), (start2, _) in zip(intervals, intervals[1:])))

    def test_latest_authorization_is_recognized_but_cannot_override_budget(self):
        self.assertTrue(self.plan["effective_protocol"]["execution_authorization"]["reduced_screen"])
        self.assertFalse(self.plan["requested_preflight"]["within_declared_budget"])
        self.assertEqual(self.plan["base_protocol"]["design_budget"], self.plan["effective_protocol"]["design_budget"])
        self.assertEqual(self.plan["base_protocol"]["independent_runs"]["reduced_screen"], 3)

    def test_export_contains_explicit_skips_null_metrics_and_no_simulator_call(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)/"export"
            with patch("src.algorithms.genetic_algorithm.evaluate_cic", side_effect=AssertionError("must not simulate")), \
                 patch("src.evaluation.monte_carlo.simulate_cic", side_effect=AssertionError("must not simulate")):
                summary = export_plan(self.plan, path)
            self.assertEqual(summary["status"], "stopped_at_preflight")
            self.assertEqual((summary["completed_GA_runs"], summary["skipped_GA_runs"]), (0, 75))
            self.assertEqual(summary["actual_screen_CIC_simulations"], 0)
            self.assertEqual(len(list((path/"runs").glob('*.json'))), 75)
            records = json.loads((path/"run_results.json").read_text())
            self.assertTrue(all(r["training_fitness"] is None and r["independent_evaluation_mean"] is None for r in records))
            with (path/"run_matrix.csv").open(newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 75)
            self.assertTrue(all(r["status"] == "not_generated_no_completed_screen_runs" for r in json.loads((path/"figure_status.json").read_text())))

    def test_invalid_replications_or_reused_main_seed_are_rejected(self):
        for changes in ({"requested_independent_runs": True}, {"requested_independent_runs": 1},
                        {"screen_master_seed": self.request["reserved_main_master_seed"]}, {"main_experiments_authorized": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan_reduced_screen({**self.request, **changes})
