"""V2 scope, disjoint seeds, verified API integration and checkpoint recovery."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import networkx as nx

from experiments.reduced_screen_v2 import (
    atomic_json, execute, export_preflight, plan_screen, reconcile_pending, run_ga_case, validate_pair,
)
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic
from src.experiments.sensitivity import FACTORS


class ReducedScreenV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((PROJECT_ROOT/"experiments/configs/milestone_7_reduced_screen_v2.json").read_text())
        cls.plan = plan_screen(cls.request)

    def test_old_matrix_two_levels_in_every_scenario(self):
        audit = self.plan["audit_previous"]
        self.assertEqual(audit["cross_scenario_pairs"], 0)
        self.assertEqual(audit["validated_pairs"], 60)
        for row in audit["scenarios"]:
            self.assertEqual(row["runs"], 25)
            self.assertTrue(all(len(row["levels"][f]) == 2 for f in FACTORS))
            self.assertEqual(row["three_level_panels"], [])

    def test_nine_unique_profiles_five_runs_on_one_control_selected_scenario(self):
        rows = self.plan["matrix"]
        self.assertEqual(len(rows), 45)
        self.assertEqual(len({r["profile_id"] for r in rows}), 9)
        self.assertEqual({r["scenario_id"] for r in rows}, {"email-Eu-core_high_1"})
        self.assertTrue(all(r["rumor_seeds"] == [926] and r["k"] == 5 and r["p"] == .03 for r in rows))
        for profile in self.plan["profiles"]:
            self.assertEqual({r["repetition_index"] for r in rows if r["profile_id"] == profile["profile_id"]}, set(range(5)))

    def test_each_panel_has_all_three_levels_and_shared_reference(self):
        for factor in FACTORS:
            rows = [r for r in self.plan["matrix"] if factor in r["OFAT_panels"]]
            self.assertEqual(len(rows), 15)
            self.assertEqual(len({r[factor] for r in rows}), 3)
            self.assertEqual(sum(r["profile_id"] == "reference" for r in rows), 5)

    def test_reference_and_monte_carlo_settings_are_unchanged(self):
        ref = next(r for r in self.plan["matrix"] if r["profile_id"] == "reference")
        for k, v in self.plan["protocol"]["reference_ga"].items():
            self.assertEqual(ref[k], v)
        self.assertTrue(all((r["S_opt"], r["S_eval"], r["final_batches"]) == (100, 6000, 2) for r in self.plan["matrix"]))

    def test_preflight_exact_bounds_and_overhead(self):
        p = self.plan["preflight"]
        self.assertEqual((p["GA_runs"], p["fitness_evaluator_calls_upper"], p["total_evaluator_calls_upper"]), (45, 8500, 8600))
        self.assertEqual((p["fitness_CIC_upper"], p["GA_final_CIC"], p["control_CIC"]), (850000, 540000, 60000))
        self.assertEqual(p["total_CIC_upper"], 1450000)
        self.assertAlmostEqual(p["projected_seconds_including_overhead"], 2898.2461189665632)
        self.assertTrue(p["within_declared_budget"])

    def test_all_optimization_seeds_distinct_and_disjoint_from_all_final_blocks(self):
        rows = self.plan["matrix"]
        self.assertEqual(len({r["GA_random_seed"] for r in rows}), 45)
        self.assertEqual(len({r["GA_operators_seed"] for r in rows}), 45)
        self.assertEqual(len({r["optimization_base_random_seed"] for r in rows}), 45)
        for a in rows:
            for b in rows:
                self.assertTrue(a["optimization_seed_stop_exclusive"] <= b["final_batch_seeds"][0] or
                                b["final_seed_stop_exclusive"] <= a["optimization_base_random_seed"])

    def test_final_batches_common_within_repetition_disjoint_between_repetitions(self):
        rows = self.plan["matrix"]
        starts = set()
        for repeat in range(5):
            schedules = {tuple(r["final_batch_seeds"]) for r in rows if r["repetition_index"] == repeat}
            self.assertEqual(len(schedules), 1)
            seeds = next(iter(schedules))
            self.assertEqual(seeds[1]-seeds[0], 6000)
            starts.add(seeds[0])
        self.assertEqual(len(starts), 5)

    def test_only_declared_factor_changes_in_all_forty_pairs(self):
        by_id = {r["run_id"]: r for r in self.plan["matrix"]}
        self.assertEqual(len(self.plan["pairs"]), 40)
        for pair in self.plan["pairs"]:
            validate_pair(by_id[pair["reference_run_id"]], by_id[pair["alternative_run_id"]], pair["factor"])

    def test_pair_rejects_cross_dataset_rumor_and_second_parameter_change(self):
        ref = self.plan["matrix"][0]
        alt = deepcopy(next(r for r in self.plan["matrix"] if r["profile_id"] == "population_size_20"))
        for key, value in (("dataset", "Wiki-Vote"), ("rumor_seeds", [858]), ("mutation_rate", .2)):
            changed = {**alt, key: value}
            with self.assertRaises(ValueError):
                validate_pair(ref, changed, "population_size")

    def test_main_seed_namespace_and_unauthorized_scope_rejected(self):
        for key, value in (("screen_master_seed", 2026111109), ("main_experiments_authorized", True),
                           ("requested_independent_runs", 3), ("scenario_id", "Wiki-Vote_high_1")):
            with self.assertRaises(ValueError):
                plan_screen({**self.request, key: value})

    def test_over_budget_stops_without_running_any_worker(self):
        plan = plan_screen({**self.request, "runtime_overhead_allowance_seconds": 10800})
        self.assertFalse(plan["preflight"]["within_declared_budget"])
        with TemporaryDirectory() as directory, patch("experiments.reduced_screen_v2.subprocess.run") as run:
            result = execute(plan, Path(directory)/"no_execution")
            self.assertEqual(result["status"], "stopped_at_preflight")
            run.assert_not_called()

    def test_preflight_exports_full_matrix_and_analysis_policy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            export_preflight(self.plan, root)
            self.assertEqual(len(json.loads((root/"matrix.json").read_text())), 45)
            self.assertEqual(json.loads((root/"analysis_policy.json").read_text())["primary_unit"], "independent_GA_run")
            self.assertTrue((root/"OFAT_panels.csv").exists())

    def small_case(self):
        graph = nx.DiGraph([(10, 30), (30, 70), (90, 30), (70, 120)])
        row = {**self.plan["matrix"][0], "rumor_seeds": [10], "k": 1, "p": .4, "S_opt": 7,
               "S_eval": 9, "population_size": 4, "max_generations": 3, "tournament_size": 2}
        return graph, row

    def test_real_api_integration_independent_evaluation_and_constraints(self):
        graph, row = self.small_case()
        before = deepcopy(graph)
        with patch("experiments.reduced_screen_v2.evaluate_cic", wraps=evaluate_cic) as final:
            result = run_ga_case(graph, row)
        self.assertEqual(final.call_count, 2)
        self.assertEqual([c.kwargs["base_random_seed"] for c in final.call_args_list], row["final_batch_seeds"])
        self.assertEqual(result["final"]["S"], 18)
        self.assertEqual(len(result["protector_seeds"]), 1)
        self.assertNotIn(10, result["protector_seeds"])
        self.assertTrue(nx.utils.graphs_equal(before, graph))
        core = result["core_GA_result"]
        self.assertEqual(result["CIC_simulations"], core["evaluation_count"]*7+18)

    def test_reproducible_P_training_history_and_final_statistics(self):
        graph, row = self.small_case()
        a, b = run_ga_case(graph, row), run_ga_case(graph, row)
        for key in ("protector_seeds", "training_fitness", "final", "CIC_simulations", "evaluator_calls"):
            self.assertEqual(a[key], b[key])
        self.assertEqual([g["best_fitness"] for g in a["core_GA_result"]["history"]],
                         [g["best_fitness"] for g in b["core_GA_result"]["history"]])

    def test_checkpoint_recovers_complete_result_without_repeating_work(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"result.json"
            atomic_json(path, {"job_fingerprint": "same", "CIC_simulations": 12, "worker_runtime_seconds": 2.5})
            state = {"pending": {"work_id": "test", "result_path": str(path), "fingerprint": "same", "CIC_upper": 20, "timeout_seconds": 30},
                     "completed": {}, "attempts": [], "charged_CIC": 0, "active_runtime_seconds": 0}
            reconcile_pending(state)
            self.assertEqual(state["charged_CIC"], 12)
            self.assertEqual(state["active_runtime_seconds"], 2.5)
            self.assertEqual(state["completed"]["test"], str(path))
            reconcile_pending(state)
            self.assertEqual(state["charged_CIC"], 12)

    def test_interruption_charges_unknown_work_conservatively(self):
        with TemporaryDirectory() as directory:
            state = {"pending": {"work_id": "lost", "result_path": str(Path(directory)/"absent.json"), "fingerprint": "same", "CIC_upper": 500, "timeout_seconds": 60},
                     "completed": {}, "attempts": [], "charged_CIC": 10, "active_runtime_seconds": 2}
            reconcile_pending(state)
            self.assertEqual((state["charged_CIC"], state["active_runtime_seconds"]), (510, 62))
            self.assertEqual(state["completed"], {})
            self.assertIsNone(state["attempts"][0]["measured_CIC"])

    def test_checkpoint_wrong_job_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"result.json"
            atomic_json(path, {"job_fingerprint": "different"})
            state = {"pending": {"result_path": str(path), "fingerprint": "expected"}}
            with self.assertRaises(ValueError):
                reconcile_pending(state)


if __name__ == "__main__":
    unittest.main()
