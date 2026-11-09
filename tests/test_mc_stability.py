"""Verify pilot batch independence, uncertainty calculations and exports."""

from copy import deepcopy
import csv
import json
from math import sqrt
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import networkx as nx

from experiments.pilot_mc_stability import (
    DEFAULT_CONFIG, recommend_simulations, run_pilot, summarize_batches, validate_config,
)
from src.data.specs import PROJECT_ROOT
from src.diffusion import simulate_cic
from src.evaluation import evaluate_cic


class StabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))

    def test_saved_config_uses_all_required_S_and_disjoint_batch_blocks(self) -> None:
        validate_config(self.config)
        self.assertEqual(self.config["simulation_counts"], [50, 100, 250, 500, 1000])
        blocks = []
        for batch in range(self.config["number_of_batches"]):
            start = self.config["first_batch_base_seed"] + batch * self.config["batch_seed_stride"]
            blocks.append(set(range(start, start + max(self.config["simulation_counts"]))))
        for first, block in enumerate(blocks):
            for other in blocks[first + 1:]:
                self.assertFalse(block & other)

    def test_overlapping_seed_blocks_are_rejected(self) -> None:
        self.config["batch_seed_stride"] = 999
        with self.assertRaisesRegex(ValueError, "overlapping"):
            validate_config(self.config)

    def test_invalid_counts_batches_or_thresholds_are_rejected(self) -> None:
        for key, value in (
            ("simulation_counts", [1, 2]), ("simulation_counts", [50, 50]),
            ("simulation_counts", []), ("simulation_counts", [True]),
            ("number_of_batches", 1), ("number_of_batches", True),
            ("first_batch_base_seed", -1), ("propagation_probability", float("nan")),
            ("opt_standard_error_fraction_of_nodes", 0),
            ("eval_standard_error_fraction_of_nodes", float("inf")),
        ):
            with self.subTest(key=key, value=value):
                changed = deepcopy(self.config)
                changed[key] = value
                with self.assertRaises(ValueError):
                    validate_config(changed)

    def test_pooled_and_between_batch_statistics_match_known_observations(self) -> None:
        rows = []
        for batch, mean in enumerate((2, 4)):
            rows.append({
                "method": "none", "simulations": 2, "batch": batch,
                "mean_rumor_count": mean, "std_rumor_population": 1,
                "standard_error": 1, "mean_protector_count": 0,
                "mean_inactive_count": 6 - mean, "evaluation_runtime_seconds": 0.1 * (batch + 1),
            })
        summary = summarize_batches(rows)[0]
        self.assertEqual(summary["mean_rumor_count"], 3)
        self.assertAlmostEqual(summary["batch_mean_std"], sqrt(2))
        self.assertAlmostEqual(summary["pooled_rumor_std_sample"], sqrt(8 / 3))
        self.assertAlmostEqual(summary["pooled_standard_error"], sqrt(2 / 3))
        self.assertEqual(summary["mean_standard_error"], 1)
        self.assertAlmostEqual(summary["mean_evaluation_runtime_seconds"], 0.15)

    def test_unmet_precision_target_is_reported_without_claiming_success(self) -> None:
        rows = [{"simulations": s, "max_standard_error": se, "pooled_rumor_std_sample": 20,
                 "mean_evaluation_runtime_seconds": 0.1} for s, se in ((50, 3), (100, 2))]
        result = recommend_simulations(rows, 100, self.config)
        self.assertEqual(result["S_eval"]["simulations"], 100)
        self.assertFalse(result["S_eval"]["target_met"])
        self.assertEqual(result["S_eval"]["estimated_simulations_for_target"], 1600)

    def test_recommendation_uses_single_batch_not_pooled_standard_error(self) -> None:
        rows = [{"simulations": s, "max_standard_error": se, "pooled_standard_error": 0.001,
                 "pooled_rumor_std_sample": 10, "mean_evaluation_runtime_seconds": 0.1}
                for s, se in ((50, 2), (100, 0.8), (250, 0.4))]
        result = recommend_simulations(rows, 100, self.config)
        self.assertEqual(result["S_opt"]["simulations"], 100)
        self.assertEqual(result["S_eval"]["simulations"], 250)

    def test_pilot_exports_replayable_observations_and_calls_only_evaluate_cic(self) -> None:
        config = deepcopy(self.config)
        config.update(dataset="unit-test-fixture", protector_budget=1, simulation_counts=[2, 3],
                      number_of_batches=2, batch_seed_stride=3, propagation_probability=1)
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        before = graph.copy()
        with TemporaryDirectory() as temporary:
            with patch("experiments.pilot_mc_stability.evaluate_cic", wraps=evaluate_cic) as evaluator:
                report = run_pilot(graph, config, Path(temporary), plot=False, progress=False)
            self.assertEqual(evaluator.call_count, 16)
            self.assertEqual(report["total_evaluations"], 16)
            self.assertEqual(report["total_cic_simulations"], 40)
            self.assertFalse(report["official_thesis_result"])
            self.assertEqual(report["data_sha256_before"], report["data_sha256_after"])
            self.assertTrue(nx.utils.graphs_equal(before, graph))
            for filename in ("config.json", "selections.csv", "batches.csv", "summary.csv", "rankings.csv", "report.json", "analysis.md"):
                self.assertTrue((Path(temporary) / filename).is_file())
            selections = {row["method"]: row["protector_seeds"] for row in report["selections"]}
            self.assertEqual(selections["none"], [])
            for method in ("random", "degree", "pagerank"):
                self.assertEqual(len(selections[method]), 1)
                self.assertNotIn(0, selections[method])
            with (Path(temporary) / "raw_results.csv").open(encoding="utf-8", newline="") as stream:
                observations = list(csv.DictReader(stream))
            self.assertEqual(len(observations), 40)
            for row in observations:
                expected_seed = config["first_batch_base_seed"] + int(row["batch"]) * 3 + int(row["simulation_index"])
                self.assertEqual(int(row["random_seed"]), expected_seed)
                direct = simulate_cic(graph, [0], selections[row["method"]], 1,
                                      random_seed=expected_seed, tie_breaking="protector-priority")
                self.assertEqual(int(row["rumor_count"]), direct.rumor_count)
                self.assertEqual(int(row["protector_count"]), direct.protector_count)
            for row in report["batches"]:
                self.assertEqual(row["standard_error"], 0)
                self.assertGreaterEqual(row["evaluation_runtime_seconds"], 0)

    def test_output_into_dataset_directories_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not write"):
            run_pilot(nx.path_graph(10), self.config, PROJECT_ROOT / "data/raw", plot=False)
