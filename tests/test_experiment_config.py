"""Configuration failures and seed scheduling before any expensive work."""

import json
from pathlib import Path
import unittest

from src.experiments import ExperimentConfig, ExperimentConfigError, load_experiment_config, make_experiment_seed_plan
from tests.experiment_helpers import experiment_values
from tests.helpers import TemporaryFilesTest


class ExperimentConfigurationTests(TemporaryFilesTest):
    def config(self, **changes):
        return ExperimentConfig.from_dict({**experiment_values(self.root), **changes})

    def test_valid_configuration_normalizes_and_includes_control(self):
        c = self.config().to_dict()
        self.assertEqual(c["algorithms"], ["no_intervention", "random"])
        self.assertEqual(c["schema_version"], 1)

    def test_single_algorithm_is_supported(self):
        values = experiment_values(self.root)
        values.pop("algorithms")
        values["algorithm"] = "degree"
        self.assertEqual(ExperimentConfig.from_dict(values).to_dict()["algorithms"], ["no_intervention", "degree"])

    def test_unknown_keys_algorithms_duplicates_and_ambiguous_selection_fail(self):
        for changes in ({"S_evall": 3}, {"algorithm": "degree"}, {"algorithms": []},
                        {"algorithms": ["random", "random"]}, {"algorithms": ["greedy"]},
                        {"algorithms": "random"}, {"schema_version": True}):
            with self.subTest(changes=changes), self.assertRaises(ExperimentConfigError):
                self.config(**changes)

    def test_required_research_settings_have_no_defaults(self):
        for name in ("S_opt", "S_eval", "p", "k", "tie_breaking", "random_seed", "independent_run_index"):
            values = experiment_values(self.root)
            values.pop(name)
            with self.subTest(name=name), self.assertRaises(ExperimentConfigError):
                ExperimentConfig.from_dict(values)

    def test_invalid_numbers_are_rejected(self):
        for changes in ({"S_opt": 0}, {"S_eval": True}, {"k": -1}, {"k": 1.5},
                        {"p": float("nan")}, {"p": float("inf")}, {"p": True}, {"p": 1.1},
                        {"random_seed": -1}, {"independent_run_index": False}, {"tie_breaking": "first"}):
            with self.subTest(changes=changes), self.assertRaises(ExperimentConfigError):
                self.config(**changes)

    def test_explicit_rumor_ids_must_be_unique_integers(self):
        for rumor in ([10, 10], [True], ["10"], "10"):
            with self.subTest(rumor=rumor), self.assertRaises(ExperimentConfigError):
                self.config(rumor_seeds=rumor)

    def test_rumor_policy_must_be_unambiguous_and_complete(self):
        values = experiment_values(self.root)
        with self.assertRaises(ExperimentConfigError):
            self.config(rumor_seed_policy={"method": "random", "count": 1, "scope": "fixed"})
        values.pop("rumor_seeds")
        for policy in ({"method": "random", "count": 1}, {"method": "degree", "count": 1, "scope": "fixed"},
                       {"method": "random", "count": -1, "scope": "per_run"}):
            with self.subTest(policy=policy), self.assertRaises(ExperimentConfigError):
                ExperimentConfig.from_dict({**values, "rumor_seed_policy": policy})
        values["rumor_seed_policy"] = {"method": "random", "count": 1, "scope": "fixed"}
        self.assertEqual(ExperimentConfig.from_dict(values).to_dict()["rumor_seed_policy"], values["rumor_seed_policy"])

    def test_optimization_requires_explicit_cost_limits_and_ga_parameters(self):
        for name in ("full_greedy", "candidate_restricted_greedy", "genetic_algorithm"):
            values = experiment_values(self.root, all_methods=True)
            values["algorithms"] = [name]
            values["limits"] = {}
            with self.subTest(name=name), self.assertRaises(ExperimentConfigError):
                ExperimentConfig.from_dict(values)
        with self.assertRaises(ExperimentConfigError):
            self.config(algorithms=["genetic_algorithm"])

    def test_invalid_ga_parameters_are_rejected(self):
        values = experiment_values(self.root, all_methods=True)
        for changes in ({"population_size": 0}, {"mutation_rate": 2}, {"crossover_rate": True},
                        {"max_generations": -1}, {"tournament_size": 5}, {"elitism_count": 5},
                        {"cache_fitness": 1}, {"fitness_base_random_seed": 100}):
            with self.subTest(changes=changes), self.assertRaises(ExperimentConfigError):
                ExperimentConfig.from_dict({**values, "ga_parameters": {**values["ga_parameters"], **changes}})

    def test_pagerank_parameters_are_explicit_and_validated(self):
        with self.assertRaises(ExperimentConfigError):
            self.config(algorithms=["pagerank"])
        for pr in ({"alpha": 1, "tol": 1e-6, "max_iter": 100}, {"alpha": 0.85, "tol": 0, "max_iter": 100}):
            with self.subTest(pr=pr), self.assertRaises(ExperimentConfigError):
                self.config(algorithms=["pagerank"], pagerank_parameters=pr)

    def test_restriction_validates_method_pool_and_types(self):
        for restriction in ([], {"method": "other"}, {"method": "degree", "size": 0},
                            {"method": "explicit", "nodes": [20, 20]}):
            with self.subTest(restriction=restriction), self.assertRaises(ExperimentConfigError):
                self.config(candidate_restriction=restriction)

    def test_seed_block_capacity_and_even_width_are_checked(self):
        for width in (1, 3, 6, True):
            with self.subTest(width=width), self.assertRaises(ExperimentConfigError):
                self.config(seed_block_size=width)
        self.assertEqual(self.config(seed_block_size=8).to_dict()["seed_block_size"], 8)

    def test_dataset_and_output_paths_are_validated(self):
        for changes in ({"dataset": "../email"}, {"output_directory": ""}, {"processed_directory": 42},
                        {"save_raw_observations": 1}, {"limits": {"max_optimization_evaluations": -1}}):
            with self.subTest(changes=changes), self.assertRaises(ExperimentConfigError):
                self.config(**changes)

    def test_unknown_dataset_requires_explicit_processed_path(self):
        values = experiment_values(self.root)
        values.pop("processed_directory")
        with self.assertRaises(ExperimentConfigError):
            ExperimentConfig.from_dict(values)
        values["dataset"] = "email-Eu-core"
        self.assertTrue(ExperimentConfig.from_dict(values).to_dict()["processed_directory"].endswith("data/processed/email-Eu-core"))

    def test_json_paths_resolve_relative_to_configuration(self):
        values = experiment_values(self.root)
        values.update(output_directory="kết quả có khoảng trắng", processed_directory="processed")
        path = self.write(json.dumps(values), "thư mục/config.json")
        config = load_experiment_config(path)
        self.assertEqual(Path(config.to_dict()["output_directory"]), (path.parent / values["output_directory"]).resolve())
        self.assertEqual(config.source_path, path.resolve())

    def test_missing_malformed_or_non_json_configuration_fails(self):
        for path in (self.root / "missing.json", self.write("{broken", "bad.json"), self.write("{}", "config.yaml"),
                     self.write("[]", "list.json")):
            with self.subTest(path=path), self.assertRaises(ExperimentConfigError):
                load_experiment_config(path)

    def test_config_copy_and_fingerprint_are_stable(self):
        config = self.config()
        values = config.to_dict()
        values["rumor_seeds"].append(20)
        self.assertEqual(config.to_dict()["rumor_seeds"], [10])
        self.assertEqual(config.fingerprint, self.config(output_directory=str(self.root / "elsewhere"), save_raw_observations=True).fingerprint)
        self.assertNotEqual(config.fingerprint, self.config(independent_run_index=1).fingerprint)


class ExperimentSeedTests(unittest.TestCase):
    def test_seed_plan_replays_and_phase_domains_are_separate(self):
        plan = make_experiment_seed_plan(2026, 3, 1000)
        self.assertEqual(plan, make_experiment_seed_plan(2026, 3, 1000))
        self.assertEqual(len({plan.ga_random_seed, plan.random_selection_seed, plan.rumor_seed_per_run}), 3)
        self.assertEqual(plan.final_base_random_seed - plan.optimization_base_random_seed, 500)

    def test_all_master_run_pairs_have_disjoint_full_blocks(self):
        plans = [make_experiment_seed_plan(master, run, 1000) for master in range(4) for run in range(4)]
        starts = sorted(plan.block_start for plan in plans)
        self.assertEqual(len(set(starts)), 16)
        self.assertTrue(all(b - a >= 1000 for a, b in zip(starts, starts[1:])))

    def test_fixed_rumor_seed_is_shared_while_per_run_phases_change(self):
        first, second = [make_experiment_seed_plan(2026, i, 1000) for i in range(2)]
        self.assertEqual(first.rumor_seed_fixed, second.rumor_seed_fixed)
        for name in ("rumor_seed_per_run", "ga_random_seed", "random_selection_seed", "final_base_random_seed"):
            self.assertNotEqual(getattr(first, name), getattr(second, name))

    def test_invalid_seed_plan_inputs_fail(self):
        for args in ((-1, 0, 10), (0, True, 10), (0, 0, 3), (0, 0, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                make_experiment_seed_plan(*args)
