"""Four-run approval, unchanged API bridge, sealed P and main checkpoint guards."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import networkx as nx

from experiments.main_experiments import (
    evaluate_on_graph, execute, load_main_plan, seal_selections, select_on_graph, work_schedule,
)
from experiments.reduced_screen_v2 import atomic_json
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic
from src.experiments.seeds import make_experiment_seed_plan


class MainExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((PROJECT_ROOT/"experiments/configs/main_experiments_protocol_v2.json").read_text())
        cls.plan = load_main_plan(cls.request)

    def test_exact_approved_matrix_counts_and_budget(self):
        p = self.plan["preflight"]
        self.assertTrue(p["within_declared_budget"])
        self.assertEqual((p["planned_primary_method_runs"], p["GA_runs"], p["conditional_Full_Greedy_rows_skipped"]), (144, 24, 24))
        self.assertEqual((p["optimization_evaluator_calls_upper"], p["final_evaluator_calls"], p["total_evaluator_calls_upper"]), (3360, 288, 3648))
        self.assertEqual((p["optimization_CIC_upper"], p["final_CIC"], p["total_CIC_upper"]), (336000, 1056000, 1392000))
        self.assertAlmostEqual(p["projected_seconds_including_safety_and_overhead"], 8889.53713221839)
        self.assertAlmostEqual(p["runtime_headroom_seconds"], 1910.4628677816108)

    def test_only_four_run_revision_is_allowed(self):
        for change in ({"p": .05}, {"proposed_independent_runs": 3}, {"execution_authorized": False},
                       {"GA": {**self.request["GA"], "population_size": 20}}):
            with self.assertRaises(ValueError):
                load_main_plan({**self.request, **change})

    def test_all_selection_units_precede_all_final_batches(self):
        schedule = work_schedule(self.plan)
        self.assertEqual(len(schedule), 432)
        self.assertTrue(all(u["kind"] == "selection" for u in schedule[:144]))
        self.assertTrue(all(u["kind"] == "final" for u in schedule[144:]))
        self.assertEqual(sum(u["CIC_upper"] for u in schedule), 1392000)
        self.assertTrue(all(u["row"]["algorithm"] != "full_greedy" for u in schedule))

    def test_namespace_and_final_seed_schedule_are_preserved(self):
        self.assertTrue(self.plan["seed_separation_audit"]["passed"])
        self.assertGreater(self.plan["seed_separation_audit"]["historical_CIC_intervals_checked"], 100)
        self.assertEqual(self.plan["seed_separation_audit"]["main_comparison_blocks"], 24)
        for scenario in self.plan["scenarios"]:
            for repeat in range(4):
                rows = [r for r in self.plan["matrix"] if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat]
                self.assertEqual(len({tuple(r["final_batch_seeds"]) for r in rows}), 1)

    def small_case(self, method="genetic_algorithm"):
        graph = nx.DiGraph([(10, 30), (30, 50), (70, 30), (50, 90), (90, 110)])
        q = deepcopy(self.request)
        q["GA"].update(population_size=4, max_generations=2, tournament_size=2)
        q["candidate_restricted_greedy"]["pool_size"] = 3
        row = deepcopy(next(r for r in self.plan["matrix"] if r["algorithm"] == method))
        row.update(rumor_seeds=[10], k=1, p=1, S_opt=3, S_eval_per_batch=4)
        return graph, q, row

    def test_each_admitted_method_uses_verified_dispatch_and_constraints(self):
        for method in ("no_intervention", "random", "degree", "pagerank", "candidate_restricted_greedy", "genetic_algorithm"):
            graph, q, row = self.small_case(method)
            before = deepcopy(graph)
            selected = select_on_graph(graph, q, row)
            self.assertEqual(len(selected["protector_seeds"]), 0 if method == "no_intervention" else 1)
            self.assertFalse(set(selected["protector_seeds"]) & {10})
            self.assertTrue(nx.utils.graphs_equal(graph, before))

    def test_one_selection_two_independent_batches_of_the_same_P(self):
        graph, q, row = self.small_case()
        selected = select_on_graph(graph, q, row)
        with patch("experiments.main_experiments.evaluate_cic", wraps=evaluate_cic) as evaluate:
            a = evaluate_on_graph(graph, row, selected["protector_seeds"], 0)
            b = evaluate_on_graph(graph, row, selected["protector_seeds"], 1)
        self.assertEqual(evaluate.call_count, 2)
        self.assertEqual([c.kwargs["base_random_seed"] for c in evaluate.call_args_list], row["final_batch_seeds"])
        self.assertEqual(a["protector_seeds"], b["protector_seeds"])
        self.assertEqual((a["CIC_simulations"], b["CIC_simulations"]), (4, 4))

    def test_directed_manual_outcome_and_count_conservation(self):
        graph, _, row = self.small_case()
        # Protector at30 is permanently active, blocks rumor from node10.
        result = evaluate_on_graph(graph, row, [30], 0)
        self.assertEqual(result["raw_counts"]["rumor_count"], [1]*4)
        for i in range(4):
            self.assertEqual(sum(result["raw_counts"][k][i] for k in ("rumor_count", "protector_count", "inactive_count")), len(graph))

    def test_selected_P_and_numeric_evaluation_reproduce(self):
        graph, q, row = self.small_case("random")
        a, b = select_on_graph(graph, q, row), select_on_graph(graph, q, row)
        self.assertEqual(a["protector_seeds"], b["protector_seeds"])
        x = evaluate_on_graph(graph, row, a["protector_seeds"], 0)
        y = evaluate_on_graph(graph, row, b["protector_seeds"], 0)
        self.assertEqual(x["raw_counts"], y["raw_counts"])
        self.assertEqual(x["statistics"], y["statistics"])

    def test_final_rejects_changed_or_invalid_P(self):
        graph, _, row = self.small_case()
        for P in ([10], [999], [30, 30], []):
            with self.assertRaises(ValueError):
                evaluate_on_graph(graph, row, P, 0)

    def test_final_barrier_rejects_missing_selection(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                seal_selections(self.plan, Path(directory), {"completed": {}, "result_sha256": {}})

    def fake_child(self, command, log_path, timeout, rss_limit, poll, memory_path):
        # Synthetic state-machine fixture, only in TemporaryDirectory, no experiment MC.
        job = json.loads(Path(command[-1]).read_text())
        row = job["row"]
        atomic_json(Path(job["result_path"]), {"job_fingerprint": job["fingerprint"], "CIC_simulations": job["CIC_upper"],
                    "worker_runtime_seconds": 0, "row": row,
                    "protector_seeds": [] if row["algorithm"] == "no_intervention" else [0, 1, 2, 3, 4],
                    "test_only": True})
        return {"returncode": 0, "reason": None, "parent_sampled_peak_RSS_bytes": 1, "measured_wall_seconds": 0}

    def test_full_matrix_checkpoint_resume_adds_no_duplicate_work(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"test_only"
            with patch("experiments.main_experiments.bounded_child", side_effect=self.fake_child) as child, \
                 patch("experiments.main_experiments.environment_metadata", return_value={}), \
                 patch("experiments.main_experiments.peak_rss_bytes", return_value=1), patch("builtins.print"):
                first = execute(self.plan, root)
                self.assertEqual(child.call_count, 432)
                self.assertEqual(first["status"], "completed")
                self.assertEqual(first["charged_CIC"], 1392000)
                self.assertTrue((root/"selection_barrier.json").exists())
                child.reset_mock()
                again = execute(self.plan, root)
                child.assert_not_called()
                self.assertEqual(len(again["completed"]), 432)
                self.assertEqual(again["charged_CIC"], first["charged_CIC"])

    def test_preflight_failure_starts_no_workers(self):
        plan = deepcopy(self.plan)
        plan["preflight"]["within_declared_budget"] = False
        with TemporaryDirectory() as directory, patch("experiments.main_experiments.bounded_child") as child:
            result = execute(plan, Path(directory)/"none")
            self.assertEqual(result["status"], "stopped_at_preflight")
            child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
