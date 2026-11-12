"""Frozen scenarios, fair contrasts, budgets, main reservations and RSS guards."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import networkx as nx

from experiments.cross_scenario_ga_confirmation import (
    bounded_child, build_plan, confirmation_worker, execute, export_plan,
    validate_confirmation_pair, work_schedule,
)
from experiments.reduced_screen_v2 import atomic_json
from src.data.specs import PROJECT_ROOT


class CrossScenarioPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((PROJECT_ROOT/"experiments/configs/cross_scenario_ga_confirmation.json").read_text())
        cls.probes = [{"dataset": d, "graph_and_copy_peak_RSS_bytes": 100*1024**2, "diffusion_calls": 0}
                      for d in ("email-Eu-core", "ego-Facebook", "Wiki-Vote")]
        cls.plan = build_plan(cls.request, cls.probes)

    def test_exact_three_profiles_three_scenarios_three_repeats(self):
        rows = self.plan["matrix"]
        self.assertEqual(len(rows), 27)
        for dataset in self.plan["protocol"]["datasets"]:
            group = [r for r in rows if r["dataset"] == dataset]
            self.assertEqual(len(group), 9)
            for pop in (10, 20, 40):
                self.assertEqual({r["repetition_index"] for r in group if r["population_size"] == pop}, {0, 1, 2})

    def test_validation_scenarios_selected_without_optimizer_scores(self):
        self.assertEqual([s["rumor_seeds"] for s in self.plan["scenarios"]], [[858], [1555], [2110]])
        self.assertTrue(all(926 not in r["rumor_seeds"] for r in self.plan["matrix"]))
        self.assertEqual(len(self.plan["scenario_control_evidence"]), 3)

    def test_reference_and_final_evaluation_settings_unchanged(self):
        for r in self.plan["matrix"]:
            for k, v in self.plan["protocol"]["reference_ga"].items():
                if k != "population_size":
                    self.assertEqual(r[k], v)
            self.assertEqual((r["k"], r["p"], r["S_opt"], r["final_batches"]), (5, .03, 100, 2))
            self.assertEqual(r["S_eval"], 6000 if r["dataset"] == "email-Eu-core" else 2500)

    def test_call_and_CIC_bounds_include_shared_controls(self):
        p = self.plan["preflight"]
        self.assertEqual((p["fitness_evaluator_calls_upper"], p["GA_final_evaluator_calls"], p["control_evaluator_calls"]), (6660, 54, 18))
        self.assertEqual((p["fitness_CIC_upper"], p["GA_final_CIC"], p["control_CIC"]), (666000, 198000, 66000))
        self.assertEqual((p["total_evaluator_calls_upper"], p["total_CIC_upper"]), (6732, 930000))
        self.assertAlmostEqual(p["projected_seconds_including_overhead"], 6359.887869784711)
        self.assertTrue(p["within_declared_budget"])

    def test_each_optimizer_unique_and_all_final_intervals_disjoint_from_optimization(self):
        rows = self.plan["matrix"]
        self.assertEqual(len({r["GA_operators_seed"] for r in rows}), 27)
        self.assertEqual(len({r["optimization_base_random_seed"] for r in rows}), 27)
        for a in rows:
            for b in rows:
                self.assertTrue(a["optimization_seed_stop_exclusive"] <= b["final_batch_seeds"][0] or
                                b["final_seed_stop_exclusive"] <= a["optimization_base_random_seed"])

    def test_shared_final_seeds_only_in_same_scenario_repetition(self):
        schedules = {}
        for r in self.plan["matrix"]:
            key = (r["scenario_id"], r["repetition_index"])
            if key in schedules:
                self.assertEqual(schedules[key], r["final_batch_seeds"])
            schedules[key] = r["final_batch_seeds"]
        self.assertEqual(len({tuple(s) for s in schedules.values()}), 9)

    def test_contrasts_reject_cross_dataset_R_or_other_GA_changes(self):
        ref = self.plan["matrix"][0]
        alt = next(r for r in self.plan["matrix"] if r["scenario_id"] == ref["scenario_id"] and r["repetition_index"] == 0 and r["population_size"] == 20)
        validate_confirmation_pair(ref, alt)
        for key, value in (("dataset", "Wiki-Vote"), ("rumor_seeds", [926]), ("mutation_rate", .2), ("S_eval", 2500)):
            with self.assertRaises(ValueError):
                validate_confirmation_pair(ref, {**alt, key: value})

    def test_holdouts_topology_only_exclude_all_previous_R_and_are_reproducible(self):
        again = build_plan(self.request, self.probes)
        self.assertEqual(again["main_reservations"], self.plan["main_reservations"])
        self.assertEqual(len(again["main_reservations"]), 6)
        for s in again["main_reservations"]:
            self.assertFalse(set(s["rumor_seeds"]) & set(s["excluded_old_R_ids"]))
            self.assertEqual(s["diffusion_observations_generated"], 0)
            self.assertIn(s["stratum"], ("high", "constant"))

    def test_reserved_main_seed_blocks_not_used_for_confirmation(self):
        reserved = self.plan["reserved_main_schedule"]
        self.assertEqual(len(reserved), 60)
        self.assertTrue(all(r["master_seed"] == 2026111109 and r["status"] == "reserved_not_executed" for r in reserved))
        for a in self.plan["matrix"]:
            for b in reserved:
                width = self.plan["protocol"]["random_seed_policy"]["block_width"]
                self.assertFalse(b["block_start"] <= a["optimization_base_random_seed"] < b["block_start"]+width)
                self.assertFalse(b["block_start"] <= a["final_batch_seeds"][0] < b["block_start"]+width)

    def test_memory_or_time_over_budget_never_starts_worker(self):
        cases = [build_plan({**self.request, "runtime_overhead_allowance_seconds": 10800}, self.probes),
                 build_plan({**self.request, "worker_RSS_limit_bytes": 1}, self.probes)]
        for plan in cases:
            self.assertFalse(plan["preflight"]["within_declared_budget"])
            with TemporaryDirectory() as directory, patch("experiments.cross_scenario_ga_confirmation.bounded_child") as child:
                self.assertEqual(execute(plan, Path(directory)/"no_run")["status"], "stopped_at_preflight")
                child.assert_not_called()

    def test_invalid_scope_repeats_and_seed_namespace_rejected(self):
        for key, value in (("main_experiments_authorized", True), ("master_seed", 2026111109), ("independent_runs", 5)):
            with self.assertRaises(ValueError):
                build_plan({**self.request, key: value}, self.probes)

    def test_schedule_controls_counted_once_after_all_GA_units(self):
        work = work_schedule(self.plan)
        self.assertEqual(len(work), 45)
        self.assertTrue(all(w["kind"] == "GA" for w in work[:27]))
        self.assertTrue(all(w["kind"] == "control" for w in work[27:]))
        self.assertEqual(sum(w["CIC_upper"] for w in work), 930000)

    def test_export_complete_matrix_reservations_and_analysis_policy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            export_plan(self.plan, root)
            self.assertEqual(len(json.loads((root/"matrix.json").read_text())), 27)
            self.assertEqual(len(json.loads((root/"reserved_main_scenarios.json").read_text())), 6)
            self.assertTrue((root/"analysis_policy.json").exists())

    def test_worker_reuses_real_bridge_and_atomically_adds_memory_metadata(self):
        graph = nx.DiGraph([(10, 30), (50, 30), (30, 80)])
        before = deepcopy(graph)
        row = {**self.plan["matrix"][0], "rumor_seeds": [10], "k": 1, "population_size": 4,
               "tournament_size": 2, "max_generations": 2, "S_opt": 2, "S_eval": 3, "p": 1}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job = root/"job.json"
            job.write_text(json.dumps({"row": row, "kind": "GA", "fingerprint": "test", "result_path": str(root/"result.json")}))
            with patch("experiments.reduced_screen_v2.load_processed_graph", return_value=graph):
                confirmation_worker(job)
            result = json.loads((root/"result.json").read_text())
            self.assertTrue(result["graph_unchanged"])
            self.assertGreater(result["worker_peak_RSS_bytes"], 0)
            self.assertEqual(result["final"]["S"], 6)
            self.assertTrue(nx.utils.graphs_equal(graph, before))
            self.assertFalse((root/"result.bridge.json").exists())

    def fake_child(self, command, log_path, timeout, rss_limit, poll, memory_path):
        # Test-only checkpoint IO; never exported as experiment observations.
        job = json.loads(Path(command[-1]).read_text())
        atomic_json(Path(job["result_path"]), {"job_fingerprint": job["fingerprint"], "CIC_simulations": 1,
                    "worker_runtime_seconds": 0, "worker_peak_RSS_bytes": 1, "test_fixture": True})
        return {"returncode": 0, "reason": None, "parent_sampled_peak_RSS_bytes": 1, "measured_wall_seconds": 0}

    def test_resume_skips_completed_GA_runs_and_shared_controls(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"test_only"
            with patch("experiments.cross_scenario_ga_confirmation.bounded_child", side_effect=self.fake_child) as child, \
                 patch("experiments.cross_scenario_ga_confirmation.environment_metadata", return_value={}), patch("builtins.print"):
                first = execute(self.plan, root)
                self.assertEqual(first["status"], "completed")
                self.assertEqual(child.call_count, 45)
                child.reset_mock()
                resumed = execute(self.plan, root)
                child.assert_not_called()
                self.assertEqual((resumed["charged_CIC"], len(resumed["completed"])), (45, 45))

    def test_resume_rejects_result_tampering_and_changed_config(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"test_only"
            with patch("experiments.cross_scenario_ga_confirmation.bounded_child", side_effect=self.fake_child), \
                 patch("experiments.cross_scenario_ga_confirmation.environment_metadata", return_value={}), patch("builtins.print"):
                state = execute(self.plan, root)
                with self.assertRaises(ValueError):
                    execute({**self.plan, "request": {**self.plan["request"], "master_seed": 1}}, root)
                Path(next(iter(state["completed"].values()))).write_text('{}')
                with self.assertRaises(ValueError):
                    execute(self.plan, root)


class ProcessResourceGuardTests(unittest.TestCase):
    def command(self, heartbeat, limit, sleep=0):
        code = "from pathlib import Path\nimport time\nfrom experiments.cross_scenario_ga_confirmation import memory_guard\n"+f"with memory_guard({limit},Path({str(heartbeat)!r}),.01):\n time.sleep({sleep})\n"
        return [sys.executable, "-c", code]

    def test_actual_child_below_limits_finishes(self):
        with TemporaryDirectory() as directory:
            heartbeat = Path(directory)/"memory.json"
            result = bounded_child(self.command(heartbeat, 2*1024**3), Path(directory)/"test.log", 10, 2*1024**3, .05, heartbeat)
            self.assertEqual(result["returncode"], 0)
            self.assertIsNone(result["reason"])

    def test_timed_out_child_is_killed(self):
        with TemporaryDirectory() as directory:
            heartbeat = Path(directory)/"memory.json"
            result = bounded_child(self.command(heartbeat, 2*1024**3, 10), Path(directory)/"test.log", .1, 2*1024**3, .02, heartbeat)
            self.assertEqual(result["reason"], "worker_timeout")
            self.assertNotEqual(result["returncode"], 0)

    def test_over_memory_child_is_killed(self):
        with TemporaryDirectory() as directory:
            heartbeat = Path(directory)/"memory.json"
            result = bounded_child(self.command(heartbeat, 1, 10), Path(directory)/"test.log", 5, 1, .02, heartbeat)
            self.assertEqual(result["reason"], "worker_RSS_limit")
            self.assertGreater(result["parent_sampled_peak_RSS_bytes"], 1)


if __name__ == "__main__":
    unittest.main()
