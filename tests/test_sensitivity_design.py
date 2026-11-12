"""OFAT invariants, physical work counts, fair seeds and variance units."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.design_protocol_v1 import build_design, load_exported_design, load_protocol
from src.data.specs import PROJECT_ROOT
from src.experiments.sensitivity import (
    build_ofat_matrix, computational_preflight, full_greedy_cost_record,
    ga_evaluation_upper_bound, sensitivity_seed_plan, variance_components,
)


class SensitivityDesignTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_protocol(PROJECT_ROOT / "experiments/configs/experiment_protocol_v1.json")
        self.panels, self.profiles = build_ofat_matrix(self.protocol["reference_ga"], self.protocol["factor_levels"])

    def test_four_panels_share_one_physical_baseline(self):
        self.assertEqual(len(self.panels), 12)
        self.assertEqual(len(self.profiles), 9)
        self.assertEqual(sum(p["profile_id"] == "reference" for p in self.panels), 4)
        self.assertEqual(sum(p["profile_id"] == "reference" for p in self.profiles), 1)

    def test_every_non_reference_profile_changes_exactly_one_factor(self):
        for p in self.profiles:
            changed = [k for k, value in p["parameters"].items() if value != self.protocol["reference_ga"][k]]
            self.assertEqual(changed, [] if p["profile_id"] == "reference" else [p["changed_factor"]])

    def test_reference_parameters_are_not_mutated(self):
        original = deepcopy(self.protocol)
        build_ofat_matrix(self.protocol["reference_ga"], self.protocol["factor_levels"])
        self.assertEqual(original, self.protocol)

    def test_candidate_levels_must_include_reference_without_duplicates(self):
        for values in ([20, 40], [10, 10, 20], [10, True, 20], [10, 2, 20]):
            levels = {**self.protocol["factor_levels"], "population_size": values}
            with self.subTest(values=values), self.assertRaises(ValueError):
                build_ofat_matrix(self.protocol["reference_ga"], levels)

    def test_evaluation_upper_bounds_match_population_generations_elites(self):
        expected = {"reference": 100, "population_size_20": 210, "population_size_40": 430,
                    "max_generations_20": 190, "max_generations_40": 370}
        for p in self.profiles:
            self.assertEqual(ga_evaluation_upper_bound(p["parameters"]), expected.get(p["profile_id"], 100))

    def test_full_reduced_pilot_preflights_and_shared_controls(self):
        design = build_design(self.protocol)
        full, reduced, pilot = [design["preflights"][name] for name in ("full_design", "reduced_screen", "pilot")]
        self.assertEqual((full["GA_runs"], full["total_evaluator_calls_upper"], full["total_CIC_upper"]), (270, 51600, 7300000))
        self.assertEqual((reduced["GA_runs"], reduced["total_evaluator_calls_upper"], reduced["total_CIC_upper"]), (45, 6408, 1026000))
        self.assertEqual((pilot["GA_runs"], pilot["total_evaluator_calls_upper"], pilot["total_CIC_upper"]), (8, 1264, 226000))
        self.assertEqual(pilot["control_evaluator_calls"], 8)
        self.assertFalse(full["within_declared_budget"])
        self.assertTrue(reduced["within_declared_budget"])
        self.assertTrue(pilot["within_declared_budget"])
        self.assertFalse(full["runtime_is_measured"])

    def test_duplicate_baseline_profiles_are_rejected_before_counting(self):
        with self.assertRaisesRegex(ValueError, "Deduplicate"):
            computational_preflight(self.protocol, [self.profiles[0], self.profiles[0]], [], 2, {}, self.protocol["design_budget"])

    def test_full_greedy_is_explicitly_skipped_on_actual_sizes(self):
        for n, calls in ((1005, 5010), (4039, 20180), (7115, 35560)):
            status = full_greedy_cost_record(n, 1, self.protocol)
            self.assertEqual(status["evaluator_calls"], calls)
            self.assertEqual(status["CIC_simulations"], calls*100)
            self.assertEqual(status["status"], "skipped")

    def test_full_and_main_remain_disabled_even_if_reduced_fits_budget(self):
        auth = self.protocol["execution_authorization"]
        self.assertFalse(auth["main_experiments"])
        self.assertFalse(auth["full_parameter_sweep"])
        self.assertFalse(auth["reduced_screen"])
        self.assertTrue(auth["bounded_pilot"])

    def test_pilot_preserves_algorithm_quality_validation_scenarios(self):
        design = build_design(self.protocol)
        self.assertFalse(set(self.protocol["pilot"]["scenario_ids"]) & set(self.protocol["validation_scenario_ids"]))
        self.assertEqual(len(design["pilot_schedule"]), 8)
        order = [r["profile"]["profile_id"] for r in design["pilot_schedule"][:4]]
        self.assertEqual(order, ["reference", "population_size_20", "population_size_20", "reference"])

    def test_exported_design_rejects_scenario_manifest_drift(self):
        design = build_design(self.protocol)
        with TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path/"protocol.json").write_text(json.dumps(self.protocol))
            (path/"design.json").write_text(json.dumps(design))
            self.assertEqual(load_exported_design(self.protocol, path)["pilot_schedule"], design["pilot_schedule"])
            design["manifest_sha256"] = "0"*64
            (path/"design.json").write_text(json.dumps(design))
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                load_exported_design(self.protocol, path)


class SensitivitySeedAndVarianceTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_protocol(PROJECT_ROOT / "experiments/configs/experiment_protocol_v1.json")

    def test_seed_replay_and_independent_scenario_run_blocks(self):
        plans = [sensitivity_seed_plan(self.protocol, scenario, run) for scenario in (3, 9) for run in (0, 1)]
        self.assertEqual(plans[0], sensitivity_seed_plan(self.protocol, 3, 0))
        blocks = sorted((p["block_start"], p["block_stop_exclusive"]) for p in plans)
        self.assertTrue(all(end <= start2 for (_, end), (start2, _) in zip(blocks, blocks[1:])))

    def test_optimization_and_two_final_batches_are_disjoint(self):
        plan = sensitivity_seed_plan(self.protocol, 3, 0)
        opt_stop = plan["optimization_base_seed"] + self.protocol["S_opt"]
        self.assertLessEqual(opt_stop, plan["final_base_seed"])
        final_stop = plan["final_base_seed"] + 2*6000
        self.assertLessEqual(final_stop, plan["block_stop_exclusive"])

    def test_invalid_run_indices_and_insufficient_seed_capacity_fail(self):
        for index in (-1, True, 100):
            with self.subTest(index=index), self.assertRaises(ValueError):
                sensitivity_seed_plan(self.protocol, 3, index)
        self.protocol["random_seed_policy"]["block_width"] = 10000
        with self.assertRaises(ValueError):
            sensitivity_seed_plan(self.protocol, 3, 0)

    def test_GA_run_units_are_not_MC_observations(self):
        result = variance_components([10, 14], [1, 1])
        self.assertEqual(result["independent_GA_runs"], 2)
        self.assertEqual(result["between_GA_run_mean_variance_including_MC"], 8)
        self.assertEqual(result["mean_conditional_MC_variance_of_final_mean"], 1)
        self.assertEqual(result["GA_variance_component_untruncated"], 7)
        self.assertTrue(result["small_run_count_warning"])

    def test_negative_variance_difference_is_preserved_not_hidden(self):
        result = variance_components([10, 10], [2, 2])
        self.assertEqual(result["GA_variance_component_untruncated"], -4)
        self.assertEqual(result["GA_variance_component_nonnegative_display"], 0)
        with self.assertRaises(ValueError):
            variance_components([10], [1])
