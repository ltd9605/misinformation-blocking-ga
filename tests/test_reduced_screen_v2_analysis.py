"""Independent-run inference, conditional MC summaries and resume IO guards."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import networkx as nx

from experiments.analyze_reduced_screen_v2 import contrast_summary, row_summary
from experiments.reduced_screen_v2 import atomic_json, execute, plan_screen, worker
from src.data.specs import PROJECT_ROOT


class ScreeningAnalysisTests(unittest.TestCase):
    def test_overlapping_differences_remain_unresolved(self):
        s = contrast_summary([-1, 1, -2, 2, 0], [.1]*5)
        self.assertEqual(s["independent_GA_pairs"], 5)
        self.assertEqual(s["conclusion"], "insufficient_evidence_of_difference")
        self.assertLess(s["Bonferroni_family_CI95_low"], 0)
        self.assertGreater(s["Bonferroni_family_CI95_high"], 0)

    def test_multiple_comparison_interval_is_wider(self):
        s = contrast_summary([-3, -1, -2, -1, -3], [.1]*5)
        self.assertLess(s["Bonferroni_family_CI95_low"], s["pointwise_CI95_low"])
        self.assertGreater(s["Bonferroni_family_CI95_high"], s["pointwise_CI95_high"])

    def test_detectable_direction_is_limited_to_this_scenario(self):
        lower = contrast_summary([-100, -101, -99, -100, -100], [.1]*5)
        higher = contrast_summary([100, 101, 99, 100, 100], [.1]*5)
        self.assertTrue(lower["conclusion"].startswith("lower_final_rumor_on_this_scenario_only"))
        self.assertTrue(higher["conclusion"].startswith("higher_final_rumor_on_this_scenario_only"))

    def test_zero_variance_is_not_claimed_as_certain_difference(self):
        s = contrast_summary([-1]*5, [0]*5)
        self.assertTrue(s["zero_empirical_variance_warning"])
        self.assertEqual(s["conclusion"], "insufficient_evidence_of_difference")

    def test_MC_and_between_GA_variation_remain_separate(self):
        s = contrast_summary([1, 2, 3, 4, 5], [2]*5)
        v = s["variance_components_of_difference"]
        self.assertAlmostEqual(v["between_GA_run_mean_variance_including_MC"], 2.5)
        self.assertEqual(v["mean_conditional_MC_variance_of_final_mean"], 4)
        self.assertEqual(v["GA_variance_component_untruncated"], -1.5)
        self.assertEqual(v["GA_variance_component_nonnegative_display"], 0)

    def test_five_final_means_are_not_treated_as_60000_GA_repetitions(self):
        s = contrast_summary([1, 2, 3, 4, 5], [0]*5)
        self.assertEqual(s["independent_GA_pairs"], 5)
        self.assertAlmostEqual(s["SE_across_GA_pairs"], (2.5/5)**.5)
        with self.assertRaises(ValueError):
            contrast_summary([1], [.1])


class CheckpointIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        request = json.loads((PROJECT_ROOT/"experiments/configs/milestone_7_reduced_screen_v2.json").read_text())
        cls.plan = plan_screen(request)

    def fake_child(self, command, **kwargs):
        # Synthetic IO fixture only, never written to experimental output.
        job = json.loads(Path(command[-1]).read_text())
        atomic_json(Path(job["result_path"]), {"job_fingerprint": job["fingerprint"], "CIC_simulations": 1,
                    "worker_runtime_seconds": 0, "fixture_only": True})
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def test_resumption_skips_all_completed_runs_and_controls(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"test_only"
            with patch("experiments.reduced_screen_v2.subprocess.run", side_effect=self.fake_child) as child, \
                 patch("experiments.reduced_screen_v2.environment_metadata", return_value={}), patch("builtins.print"):
                first = execute(self.plan, root)
                self.assertEqual(first["status"], "completed")
                self.assertEqual(child.call_count, 55)
                child.reset_mock()
                second = execute(self.plan, root)
                child.assert_not_called()
                self.assertEqual(second["charged_CIC"], 55)
                self.assertEqual(len(second["completed"]), 55)

    def test_resume_rejects_modified_result_and_changed_configuration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/"test_only"
            with patch("experiments.reduced_screen_v2.subprocess.run", side_effect=self.fake_child), \
                 patch("experiments.reduced_screen_v2.environment_metadata", return_value={}), patch("builtins.print"):
                state = execute(self.plan, root)
                with self.assertRaises(ValueError):
                    execute({**self.plan, "request": {**self.plan["request"], "screen_master_seed": 5}}, root)
                Path(next(iter(state["completed"].values()))).write_text('{}')
                with self.assertRaises(ValueError):
                    execute(self.plan, root)

    def test_worker_real_APIs_save_complete_JSON_and_graph_is_unchanged(self):
        graph = nx.DiGraph([(10, 50), (80, 50), (50, 120)])
        before = deepcopy(graph)
        row = {**self.plan["matrix"][0], "k": 1, "rumor_seeds": [10], "p": 1, "S_opt": 2, "S_eval": 3,
               "population_size": 4, "max_generations": 2, "tournament_size": 2}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/"result.json"
            job_path = root/"job.json"
            atomic_json(job_path, {"kind": "GA", "row": row, "fingerprint": "test", "result_path": str(path)})
            with patch("experiments.reduced_screen_v2.load_processed_graph", return_value=graph):
                worker(job_path)
            result = json.loads(path.read_text())
            summary = row_summary(result, {"rumor_mean": 3})
            self.assertTrue(result["graph_unchanged"])
            self.assertTrue(nx.utils.graphs_equal(graph, before))
            self.assertEqual(summary["final_simulations"], 6)
            self.assertAlmostEqual(summary["spread_reduction_fraction"], 1-summary["independent_mean"]/3)
            self.assertEqual(summary["generations_run"], 2)


if __name__ == "__main__":
    unittest.main()
