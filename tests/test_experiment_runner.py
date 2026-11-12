"""Processed-fixture integration across all seven methods and exported evidence."""

from contextlib import ExitStack
from copy import deepcopy
import csv
import json
from pathlib import Path
from random import Random
from statistics import mean, pstdev
import subprocess
import sys
from unittest.mock import patch

import networkx as nx

from src.data import DatasetValidationError, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments import ExperimentConfig, ExperimentConfigError, ExperimentLimitError, run_experiment
from src.experiments import runner
from tests.experiment_helpers import experiment_values, processed_fixture
from tests.helpers import TemporaryFilesTest


def scientific_rows(result):
    return [{key: value for key, value in row.items() if not key.endswith(("_seconds", "_runtime_seconds"))}
            for row in result.rows]


class ExperimentRunnerTests(TemporaryFilesTest):
    def setUp(self):
        super().setUp()
        self.graph = processed_fixture(self.root)
        self.values = experiment_values(self.root, all_methods=True)

    def config(self, **changes):
        return ExperimentConfig.from_dict({**self.values, **changes})

    def run_case(self, **changes):
        return run_experiment(self.config(**changes))

    def test_all_methods_share_protocol_and_return_valid_protectors(self):
        result = self.run_case()
        self.assertEqual(len(result.rows), 7)
        for row in result.rows:
            self.assertEqual((row["rumor_seeds"], row["k"], row["p"], row["tie_breaking"], row["S_eval"]),
                             ([10], 1, 0.4, "protector-priority", 4))
            expected = 0 if row["algorithm"] == "no_intervention" else 1
            self.assertEqual(len(set(row["protector_seeds"])), expected)
            self.assertFalse(set(row["protector_seeds"]) & {10})
            self.assertTrue(set(row["protector_seeds"]) <= set(self.graph))
            self.assertEqual(row["rumor_mean"] + row["protector_mean"] + row["inactive_mean"], 6)

    def test_hand_checked_directed_chain_metrics_and_full_greedy(self):
        result = self.run_case(p=1)
        rows = {row["algorithm"]: row for row in result.rows}
        self.assertEqual(rows["no_intervention"]["rumor_mean"], 4)
        for name in ("degree", "full_greedy", "candidate_restricted_greedy"):
            self.assertEqual(rows[name]["protector_seeds"], [20])
            self.assertEqual(rows[name]["rumor_mean"], 1)
            self.assertEqual(rows[name]["protector_mean"], 3)
            self.assertEqual(rows[name]["rumor_reduction_percent"], 75)
            self.assertEqual(rows[name]["rumor_standard_error"], 0)

    def test_undirected_graph_is_supported(self):
        processed_fixture(self.root, directed=False)
        result = self.run_case(p=1)
        self.assertFalse(result.metadata["graph"]["directed"])
        self.assertEqual(result.rows[0]["rumor_mean"], 5)

    def test_p_zero_has_no_spread(self):
        result = self.run_case(p=0)
        for row in result.rows:
            self.assertEqual(row["rumor_mean"], 1)
            self.assertEqual(row["rumor_std_population"], 0)
            self.assertEqual(row["rumor_reduction_percent"], 0)

    def test_single_final_observation_exports_null_uncertainty(self):
        result = self.run_case(S_eval=1)
        self.assertTrue(all(row["rumor_standard_error"] is None for row in result.rows))
        self.assertEqual(result.summary["total_final_evaluations"], 7)

    def test_k_zero_reuses_control_without_charging_duplicate_final_calls(self):
        result = self.run_case(k=0)
        self.assertEqual(result.summary["total_final_evaluations"], 1)
        self.assertEqual(result.summary["total_optimization_evaluations"], 1)  # Cached GA empty genotype.
        self.assertEqual(result.summary["total_cic_simulations"], 2 + 4)
        for row in result.rows:
            self.assertEqual(row["protector_seeds"], [])
            self.assertEqual(row["final_evaluation_id"], "no_intervention")
            if row["algorithm"] != "no_intervention":
                self.assertTrue(row["reused_control_evaluation"])
                self.assertEqual(row["final_evaluation_runtime_seconds"], 0)

    def test_no_rumor_seeds_produce_null_relative_reduction(self):
        result = self.run_case(rumor_seeds=[])
        for row in result.rows:
            self.assertEqual(row["rumor_mean"], 0)
            self.assertIsNone(row["rumor_reduction_percent"])

    def test_replay_matches_statistics_protectors_seeds_and_convergence(self):
        first = self.run_case()
        second = self.run_case(output_directory=str(self.root / "replay"))
        self.assertEqual(scientific_rows(first), scientific_rows(second))
        self.assertEqual(first.metadata["seed_plan"], second.metadata["seed_plan"])
        def history(result):
            with (result.output_directory / "convergence.csv").open(newline="") as stream:
                return [{k: v for k, v in row.items() if not k.endswith("_seconds")}
                        for row in csv.DictReader(stream)]
        self.assertEqual(history(first), history(second))

    def test_method_order_does_not_change_scientific_results(self):
        first = self.run_case()
        second = self.run_case(algorithms=list(reversed(self.values["algorithms"])),
                               output_directory=str(self.root / "reordered"))
        self.assertEqual({r["algorithm"]: r for r in scientific_rows(first)},
                         {r["algorithm"]: r for r in scientific_rows(second)})

    def test_every_selection_precedes_final_evaluations_and_intervals_are_disjoint(self):
        events = []
        final_calls = []
        def wrap_selection(name, original):
            def wrapped(*args, **kwargs):
                events.append(name)
                return original(*args, **kwargs)
            return wrapped
        original_evaluate = runner.evaluate_cic
        def final(*args, **kwargs):
            events.append("final")
            final_calls.append((args, kwargs))
            return original_evaluate(*args, **kwargs)
        with ExitStack() as stack:
            for name in ("select_random", "select_degree", "select_pagerank", "select_greedy",
                         "select_candidate_restricted_greedy", "select_genetic_algorithm"):
                stack.enter_context(patch.object(runner, name, side_effect=wrap_selection(name, getattr(runner, name))))
            stack.enter_context(patch.object(runner, "evaluate_cic", side_effect=final))
            result = self.run_case()
        first_final = events.index("final")
        self.assertTrue(all(event == "final" for event in events[first_final:]))
        self.assertEqual(len(final_calls), 7)
        opt, holdout = result.metadata["seed_intervals"].values()
        self.assertLess(opt[1], holdout[0])
        for args, kwargs in final_calls:
            self.assertEqual((args[1], args[3], args[4]), ((10,), 0.4, 4))
            self.assertEqual(kwargs, {"base_random_seed": holdout[0], "tie_breaking": "protector-priority"})
        details = json.loads((result.output_directory / "selection_details.json").read_text())
        for name in ("full_greedy", "candidate_restricted_greedy"):
            self.assertEqual(details[name]["base_random_seed"], opt[0])
        self.assertEqual(details["genetic_algorithm"]["seeds"]["fitness_base_random_seed"], opt[0])

    def test_fixed_rumor_policy_is_shared_across_independent_runs(self):
        values = deepcopy(self.values)
        values.pop("rumor_seeds")
        values["rumor_seed_policy"] = {"method": "random", "count": 2, "scope": "fixed"}
        first = run_experiment(ExperimentConfig.from_dict(values))
        second = run_experiment(ExperimentConfig.from_dict({**values, "independent_run_index": 1}))
        self.assertEqual(first.metadata["resolved_rumor_seeds"], second.metadata["resolved_rumor_seeds"])
        self.assertNotEqual(first.metadata["seed_plan"]["final_base_random_seed"], second.metadata["seed_plan"]["final_base_random_seed"])

    def test_per_run_rumor_policy_uses_logged_seed_and_sorted_node_universe(self):
        values = deepcopy(self.values)
        values.pop("rumor_seeds")
        values["rumor_seed_policy"] = {"method": "random", "count": 2, "scope": "per_run"}
        result = run_experiment(ExperimentConfig.from_dict(values))
        expected = sorted(Random(result.metadata["seed_plan"]["rumor_seed_per_run"]).sample(sorted(self.graph), 2))
        self.assertEqual(result.metadata["resolved_rumor_seeds"], expected)

    def test_full_greedy_cost_is_exact_and_runtime_is_not_predicted(self):
        result = self.run_case(k=2)
        costs = json.loads((result.output_directory / "preflight.json").read_text())
        self.assertEqual(costs["full_greedy"]["optimization_evaluation_upper_bound"], 9)
        self.assertEqual(costs["full_greedy"]["optimization_cic_simulation_upper_bound"], 18)
        self.assertIsNone(costs["full_greedy"]["runtime_prediction_seconds"])
        row = next(row for row in result.rows if row["algorithm"] == "full_greedy")
        self.assertEqual(row["optimization_evaluation_count"], 9)
        self.assertGreaterEqual(row["selection_runtime_seconds"], row["optimization_evaluator_seconds"])

    def test_full_greedy_limit_blocks_every_method_before_selection_or_evaluation(self):
        limits = {**self.values["limits"], "max_full_greedy_evaluations": 4}
        config = self.config(limits=limits)
        with patch.object(runner, "_select") as selector, patch.object(runner, "evaluate_cic") as evaluator:
            with self.assertRaisesRegex(ExperimentLimitError, "Full Greedy blocked"):
                run_experiment(config)
        selector.assert_not_called()
        evaluator.assert_not_called()
        self.assertFalse(config.run_directory.exists())

    def test_full_greedy_cic_limit_is_checked_separately(self):
        with self.assertRaises(ExperimentLimitError):
            self.run_case(limits={**self.values["limits"], "max_full_greedy_cic_simulations": 9})

    def test_generic_optimizer_limits_block_before_work(self):
        for limit in ("max_optimization_evaluations", "max_optimization_cic_simulations"):
            with self.subTest(limit=limit), self.assertRaises(ExperimentLimitError):
                self.run_case(limits={**self.values["limits"], limit: 0})

    def test_candidate_restricted_is_named_and_uses_explicit_pool(self):
        result = self.run_case(algorithms=["candidate_restricted_greedy"],
                               candidate_restriction={"method": "explicit", "nodes": [40, 50]})
        self.assertEqual(result.rows[1]["algorithm"], "candidate_restricted_greedy")
        self.assertTrue(set(result.rows[1]["protector_seeds"]) <= {40, 50})

    def test_bad_candidate_pools_rumor_seeds_and_budgets_fail_before_work(self):
        invalid = ({"rumor_seeds": [999]}, {"k": 6},
                   {"candidate_restriction": {"method": "explicit", "nodes": [10, 20]}},
                   {"candidate_restriction": {"method": "explicit", "nodes": [999]}},
                   {"candidate_restriction": {"method": "degree", "size": 6}})
        with patch.object(runner, "_select") as selector:
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ExperimentConfigError):
                    self.run_case(**changes)
        selector.assert_not_called()

    def test_excessive_rumor_policy_count_fails(self):
        values = deepcopy(self.values)
        values.pop("rumor_seeds")
        values["rumor_seed_policy"] = {"method": "random", "count": 7, "scope": "fixed"}
        with self.assertRaises(ExperimentConfigError):
            run_experiment(ExperimentConfig.from_dict(values))

    def test_processed_checksums_and_dataset_label_are_validated(self):
        with self.assertRaisesRegex(ExperimentConfigError, "Dataset label"):
            self.run_case(dataset="wrong-label")
        with (self.root / "processed/nodes.csv").open("a") as stream:
            stream.write("999\n")
        with self.assertRaises(DatasetValidationError):
            self.run_case()

    def test_graph_and_processed_bytes_are_unchanged(self):
        source = self.root / "processed"
        before = {p.name: p.read_bytes() for p in source.iterdir()}
        result = self.run_case()
        self.assertTrue(nx.utils.graphs_equal(load_processed_graph(source), self.graph))
        self.assertEqual(before, {p.name: p.read_bytes() for p in source.iterdir()})
        self.assertTrue(result.metadata["graph_unchanged"])
        self.assertTrue(result.metadata["processed_artifacts_unchanged"])

    def test_attribute_mutation_is_detected_before_final_evaluation(self):
        original = runner.select_degree
        def mutate(graph, *args, **kwargs):
            graph.nodes[10]["unexpected"] = True
            return original(graph, *args, **kwargs)
        with patch.object(runner, "select_degree", side_effect=mutate), patch.object(runner, "evaluate_cic") as final:
            with self.assertRaisesRegex(RuntimeError, "modified the input graph"):
                self.run_case(algorithms=["degree"])
        final.assert_not_called()

    def test_invalid_protector_output_is_rejected(self):
        with patch.object(runner, "select_degree", return_value=frozenset([10])):
            with self.assertRaisesRegex(RuntimeError, "protector constraints"):
                self.run_case(algorithms=["degree"])

    def test_existing_run_is_not_overwritten(self):
        result = self.run_case()
        contents = (result.output_directory / "results.csv").read_bytes()
        with patch.object(runner, "load_processed_graph") as load:
            with self.assertRaises(FileExistsError):
                self.run_case()
        load.assert_not_called()
        self.assertEqual(contents, (result.output_directory / "results.csv").read_bytes())

    def test_output_inside_source_dataset_is_rejected(self):
        with self.assertRaisesRegex(ExperimentConfigError, "dataset directories"):
            self.run_case(output_directory=str(self.root / "processed"))

    def test_failed_final_evaluation_publishes_no_partial_result(self):
        config = self.config()
        with patch.object(runner, "evaluate_cic", side_effect=RuntimeError("test failure")):
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                run_experiment(config)
        self.assertFalse(config.run_directory.exists())
        self.assertFalse(list(config.run_directory.parent.glob(".experiment-*")))

    def test_csv_json_convergence_and_optional_raw_observations(self):
        result = self.run_case(save_raw_observations=True)
        names = {p.name for p in result.output_directory.iterdir()}
        self.assertEqual(names, {"results.csv", "config.json", "metadata.json", "summary.json", "preflight.json",
                                 "selection_details.json", "convergence.csv", "raw_observations.csv", "method_status.csv"})
        for name in ("config", "metadata", "summary", "preflight", "selection_details"):
            json.loads((result.output_directory / f"{name}.json").read_text())
        with (result.output_directory / "results.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 7)
        self.assertEqual(json.loads(rows[0]["rumor_seeds"]), [10])
        with (result.output_directory / "convergence.csv").open(newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 3)  # generation 0 plus two transitions.
        with (result.output_directory / "raw_observations.csv").open(newline="") as stream:
            observations = list(csv.DictReader(stream))
        self.assertEqual(len(observations), 7 * 4)
        base = result.metadata["seed_plan"]["final_base_random_seed"]
        for observation in observations:
            self.assertEqual(int(observation["random_seed"]), base + int(observation["simulation_index"]))
        for row in result.rows:
            counts = [int(o["rumor_count"]) for o in observations if o["algorithm"] == row["algorithm"]]
            self.assertEqual(row["rumor_mean"], mean(counts))
            self.assertEqual(row["rumor_std_population"], pstdev(counts))

    def test_raw_observations_are_opt_in_and_non_ga_has_no_convergence(self):
        result = self.run_case(algorithms=["random"])
        self.assertFalse((result.output_directory / "raw_observations.csv").exists())
        self.assertFalse((result.output_directory / "convergence.csv").exists())

    def test_provenance_artifact_hashes_and_runtime_accounting(self):
        result = self.run_case()
        metadata = result.metadata
        for key in ("python", "libraries", "os", "machine", "logical_cpu_count", "physical_memory_bytes", "git_commit", "git_dirty", "source_sha256"):
            self.assertIn(key, metadata["environment"])
        for name, digest in metadata["artifact_sha256"].items():
            self.assertEqual(sha256_file(result.output_directory / name), digest)
        timings = metadata["timings"]
        self.assertEqual(timings["selection_optimization_seconds"], sum(r["selection_runtime_seconds"] for r in result.rows))
        self.assertEqual(timings["final_evaluation_seconds"], sum(r["final_evaluation_runtime_seconds"] for r in result.rows))
        self.assertAlmostEqual(timings["total_experiment_runtime_seconds"], sum(timings[k] for k in
            ("graph_loading_seconds", "selection_optimization_seconds", "final_evaluation_seconds",
             "primary_artifact_write_seconds", "orchestration_other_seconds")))
        self.assertEqual(timings["preprocessing_seconds"], 0)
        self.assertAlmostEqual(sum(metadata["orchestration_runtime_breakdown"].values()),
                               timings["orchestration_other_seconds"])

    def test_skipped_method_statuses_have_reasons_and_no_calls(self):
        result = self.run_case(algorithms=["random"], skipped_algorithms={"full_greedy": "pilot computational budget"})
        statuses = {row["algorithm"]: row for row in result.metadata["method_statuses"]}
        self.assertEqual(len(statuses), 7)
        self.assertEqual(statuses["random"]["status"], "completed")
        self.assertEqual(statuses["full_greedy"]["status"], "skipped")
        self.assertEqual(statuses["full_greedy"]["reason"], "pilot computational budget")
        self.assertEqual(statuses["degree"]["reason"], "not_selected_in_configuration")
        self.assertEqual(sum(s["final_evaluation_count"] for s in statuses.values()), 2)
        self.assertEqual(statuses["full_greedy"]["cic_simulations"], 0)

    def test_control_reuse_is_completed_rather_than_skipped(self):
        result = self.run_case(k=0)
        self.assertTrue(all(s["status"] == "completed" for s in result.summary["method_statuses"]))
        statuses = {s["algorithm"]: s for s in result.summary["method_statuses"]}
        self.assertEqual(statuses["random"]["reason"], "reused_empty_protector_control")

    def test_cli_runs_from_another_directory_with_unicode_paths(self):
        values = {**self.values, "algorithms": ["random"], "output_directory": "kết quả mới"}
        path = self.write(json.dumps(values), "cấu hình có dấu/config.json")
        completed = subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "main.py"), "experiment", "--config", str(path)],
                                   cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Methods: 2", completed.stdout)
        self.assertTrue(list((path.parent / "kết quả mới").rglob("results.csv")))

    def test_cli_run_index_and_output_overrides(self):
        values = {**self.values, "algorithms": ["degree"]}
        path = self.write(json.dumps(values), "config.json")
        completed = subprocess.run([sys.executable, "-B", "-m", "experiments.run_experiment", "--config", str(path),
                                    "--run-index", "3", "--output-dir", str(self.root / "override")],
                                   cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        saved = next((self.root / "override").rglob("config.json"))
        self.assertEqual(json.loads(saved.read_text())["independent_run_index"], 3)

    def test_cli_invalid_input_has_clear_failure_without_traceback(self):
        path = self.write("{}", "invalid.json")
        completed = subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "main.py"), "experiment", "--config", str(path)],
                                   cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Experiment failed", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
