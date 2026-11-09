"""Monte Carlo aggregation, replay, validation and processed-data integration."""

from copy import deepcopy
from dataclasses import asdict, replace
from math import sqrt
import random
import unittest
from unittest.mock import patch

import networkx as nx

from src.data import load_processed_graph
from src.data.specs import DATASETS, PROJECT_ROOT
from src.diffusion import CICLayer, CICResult, simulate_cic
from src.evaluation import MonteCarloResult, evaluate_cic


def evaluate(graph, rumor=(0,), protector=(3,), p=0.5, simulations=3,
             base=42, rule="protector-priority") -> MonteCarloResult:
    """Supply a fully explicit CIC/Monte Carlo configuration in tests."""
    return evaluate_cic(
        graph, rumor, protector, p, simulations,
        base_random_seed=base, tie_breaking=rule,
    )


class MonteCarloTests(unittest.TestCase):
    def test_same_configuration_reproduces_statistics_and_raw_results(self) -> None:
        graph = nx.gnp_random_graph(20, 0.2, seed=7, directed=True)
        first = evaluate(graph, simulations=10)
        second = evaluate(graph, simulations=10)
        self.assertEqual(first, second)
        self.assertEqual(first.raw_results, second.raw_results)
        self.assertGreaterEqual(first.runtime_seconds, 0)
        self.assertGreaterEqual(second.runtime_seconds, 0)

    def test_single_simulation_matches_cic_and_has_zero_std(self) -> None:
        graph = nx.path_graph(5)
        direct = simulate_cic(graph, [0], [3], 0.4, tie_breaking="protector-priority", random_seed=42)
        result = evaluate(graph, p=0.4, simulations=1)
        self.assertEqual(result.number_of_simulations, 1)
        self.assertEqual(result.std_rumor_count, 0)
        self.assertEqual(result.mean_rumor_count, direct.rumor_count)
        self.assertEqual(result.mean_protector_count, direct.protector_count)
        self.assertEqual(result.mean_inactive_count, direct.inactive_count)
        self.assertEqual((result.min_rumor_count, result.max_rumor_count), (direct.rumor_count,) * 2)
        self.assertEqual(result.raw_results[0].steps, direct.steps)
        self.assertEqual(result.raw_results[0].random_seed, 42)

    def test_p_zero_has_exact_counts_and_zero_std(self) -> None:
        result = evaluate(nx.path_graph(5), p=0, simulations=5)
        self.assertEqual(result.mean_rumor_count, 1)
        self.assertEqual(result.mean_protector_count, 1)
        self.assertEqual(result.mean_inactive_count, 3)
        self.assertEqual(result.std_rumor_count, 0)
        self.assertEqual((result.min_rumor_count, result.max_rumor_count), (1, 1))
        self.assertTrue(all(run.steps == 0 for run in result.raw_results))

    def test_p_one_on_a_small_competitive_graph_is_deterministic(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        result = evaluate(graph, [0], [1], p=1, simulations=4)
        self.assertEqual((result.mean_rumor_count, result.mean_protector_count, result.mean_inactive_count), (1, 3, 0))
        self.assertEqual(result.std_rumor_count, 0)
        self.assertTrue(all(run.steps == 2 for run in result.raw_results))

    def test_good_protector_on_a_chain_beats_a_hand_checked_configuration(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        near = evaluate(graph, [0], [1], p=1, simulations=5)
        far = evaluate(graph, [0], [3], p=1, simulations=5)
        self.assertEqual(near.mean_rumor_count, 1)
        self.assertEqual(far.mean_rumor_count, 3)
        self.assertLessEqual(near.mean_rumor_count, far.mean_rumor_count)
        self.assertEqual(near.std_rumor_count, 0)
        self.assertEqual(far.std_rumor_count, 0)
        self.assertEqual([run.random_seed for run in near.raw_results], [run.random_seed for run in far.raw_results])

    def test_aggregation_matches_known_counts_and_population_std(self) -> None:
        # Controlled unit-test observations, not measured experiment results.
        observations = []
        for r, p in ((1, 2), (2, 1), (3, 1)):
            rumor, protector = frozenset(range(r)), frozenset(range(6 - p, 6))
            inactive = frozenset(range(6)) - rumor - protector
            layers = (
                CICLayer(frozenset({0}), frozenset({5})),
                CICLayer(rumor - {0}, protector - {5}),
            )
            observations.append(CICResult(rumor, protector, inactive, layers))
        with patch("src.evaluation.monte_carlo.simulate_cic", side_effect=observations) as cic:
            result = evaluate(nx.complete_graph(6), [0], [5], simulations=3, base=100)
        self.assertEqual(cic.call_count, 3)
        self.assertEqual(result.mean_rumor_count, 2)
        self.assertAlmostEqual(result.std_rumor_count, sqrt(2 / 3))
        self.assertAlmostEqual(result.mean_protector_count, 4 / 3)
        self.assertAlmostEqual(result.mean_inactive_count, 8 / 3)
        self.assertEqual((result.min_rumor_count, result.max_rumor_count), (1, 3))
        self.assertEqual([run.rumor_count for run in result.raw_results], [1, 2, 3])

    def test_every_run_calls_the_verified_cic_with_the_exact_configuration(self) -> None:
        graph = nx.path_graph(5)
        with patch("src.evaluation.monte_carlo.simulate_cic", wraps=simulate_cic) as cic:
            result = evaluate(graph, simulations=4, base=7, rule="rumor-priority")
        self.assertEqual(cic.call_count, 4)
        for index, call in enumerate(cic.call_args_list):
            self.assertIs(call.args[0], graph)
            self.assertEqual(call.args[1:], (frozenset({0}), frozenset({3}), 0.5))
            self.assertEqual(call.kwargs, {"tie_breaking": "rumor-priority", "random_seed": 7 + index})
        self.assertEqual([run.simulation_index for run in result.raw_results], [0, 1, 2, 3])

    def test_raw_results_can_be_replayed_directly_with_cic(self) -> None:
        graph = nx.gnp_random_graph(15, 0.2, seed=13, directed=True)
        result = evaluate(graph, simulations=5, base=100)
        for run in result.raw_results:
            direct = simulate_cic(graph, [0], [3], 0.5,
                                  tie_breaking="protector-priority", random_seed=run.random_seed)
            self.assertEqual(
                (run.rumor_count, run.protector_count, run.inactive_count, run.steps),
                (direct.rumor_count, direct.protector_count, direct.inactive_count, direct.steps),
            )

    def test_seed_schedule_is_deterministic_and_unique(self) -> None:
        result = evaluate(nx.path_graph(5), simulations=5, base=10)
        self.assertEqual([run.random_seed for run in result.raw_results], [10, 11, 12, 13, 14])
        self.assertEqual(result.base_random_seed, 10)

    def test_zero_base_seed_is_valid(self) -> None:
        result = evaluate(nx.path_graph(5), simulations=2, base=0)
        self.assertEqual([run.random_seed for run in result.raw_results], [0, 1])

    def test_increasing_simulation_count_preserves_existing_observations(self) -> None:
        graph = nx.gnp_random_graph(15, 0.2, seed=7, directed=True)
        short = evaluate(graph, simulations=3)
        long = evaluate(graph, simulations=5)
        self.assertEqual(short.raw_results, long.raw_results[:3])

    def test_generator_seeds_are_reused_in_every_simulation(self) -> None:
        graph = nx.path_graph(5)
        from_lists = evaluate(graph, [0, 0], [3, 3], p=1)
        from_generators = evaluate(graph, iter([0, 0]), iter([3, 3]), p=1)
        self.assertEqual(from_lists, from_generators)
        self.assertTrue(all(run.rumor_count == 2 for run in from_generators.raw_results))

    def test_seed_lists_are_unchanged(self) -> None:
        rumor, protector = [0, 0], [3, 3]
        evaluate(nx.path_graph(5), rumor, protector)
        self.assertEqual(rumor, [0, 0])
        self.assertEqual(protector, [3, 3])

    def test_graph_topology_and_attributes_are_unchanged(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (3, 2), (2, 2)])
        graph.graph["label"] = "input"
        graph.nodes[2]["state"] = "inactive"
        graph.edges[0, 1]["weight"] = 0
        before = deepcopy(graph)
        evaluate(nx.freeze(graph), simulations=4)
        self.assertTrue(nx.utils.graphs_equal(before, graph))

    def test_global_rng_state_is_unchanged(self) -> None:
        before = random.getstate()
        evaluate(nx.path_graph(5), simulations=4)
        self.assertEqual(before, random.getstate())

    def test_node_edge_and_seed_insertion_order_do_not_change_statistics(self) -> None:
        first = nx.gnp_random_graph(12, 0.3, seed=7, directed=True)
        second = nx.DiGraph()
        second.add_nodes_from(reversed(list(first)))
        second.add_edges_from(reversed(list(first.edges())))
        self.assertEqual(
            evaluate(first, [0, 1], [3, 4], simulations=5),
            evaluate(second, [1, 0], [4, 3], simulations=5),
        )

    def test_means_and_raw_counts_conserve_graph_size(self) -> None:
        graph = nx.gnp_random_graph(20, 0.2, seed=13, directed=True)
        result = evaluate(graph, simulations=10)
        self.assertAlmostEqual(
            result.mean_rumor_count + result.mean_protector_count + result.mean_inactive_count, len(graph),
        )
        for run in result.raw_results:
            self.assertEqual(run.rumor_count + run.protector_count + run.inactive_count, len(graph))

    def test_both_empty_seed_sets_leave_every_node_inactive(self) -> None:
        result = evaluate(nx.path_graph(5), [], [], p=1)
        self.assertEqual((result.mean_rumor_count, result.mean_protector_count, result.mean_inactive_count), (0, 0, 5))
        self.assertEqual(result.std_rumor_count, 0)
        self.assertEqual(len(result.raw_results), 3)

    def test_empty_graph_returns_zero_statistics(self) -> None:
        result = evaluate(nx.DiGraph(), [], [], simulations=2)
        self.assertEqual((result.min_rumor_count, result.max_rumor_count, result.std_rumor_count), (0, 0, 0))
        self.assertEqual(result.mean_inactive_count, 0)

    def test_runtime_measures_the_whole_evaluation_interval(self) -> None:
        with patch("src.evaluation.monte_carlo.perf_counter", side_effect=[10.0, 10.25]):
            result = evaluate(nx.path_graph(5))
        self.assertEqual(result.runtime_seconds, 0.25)

    def test_runtime_is_recorded_but_excluded_from_reproducible_value_equality(self) -> None:
        result = evaluate(nx.path_graph(5))
        self.assertEqual(result, replace(result, runtime_seconds=result.runtime_seconds + 1))
        self.assertIn("runtime_seconds", asdict(result))

    def test_invalid_simulation_count_values_are_rejected(self) -> None:
        for simulations in (0, -1):
            with self.subTest(simulations=simulations):
                with self.assertRaisesRegex(ValueError, "number_of_simulations"):
                    evaluate(nx.path_graph(5), simulations=simulations)

    def test_invalid_simulation_count_types_are_rejected(self) -> None:
        for simulations in (True, None, 1.5, "3"):
            with self.subTest(simulations=simulations):
                with self.assertRaisesRegex(TypeError, "number_of_simulations"):
                    evaluate(nx.path_graph(5), simulations=simulations)

    def test_negative_base_seed_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "base_random_seed"):
            evaluate(nx.path_graph(5), base=-1)

    def test_invalid_base_seed_types_are_rejected(self) -> None:
        for base in (True, None, 1.5, "42"):
            with self.subTest(base=base):
                with self.assertRaisesRegex(TypeError, "base_random_seed"):
                    evaluate(nx.path_graph(5), base=base)

    def test_invalid_graph_types_are_rejected_by_cic(self) -> None:
        for graph in (None, [(0, 1)], nx.MultiGraph(), nx.MultiDiGraph()):
            with self.subTest(graph=type(graph)):
                with self.assertRaisesRegex(TypeError, "simple NetworkX"):
                    evaluate(graph)

    def test_invalid_probability_values_are_rejected_by_cic(self) -> None:
        for p in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(p=p):
                with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
                    evaluate(nx.path_graph(5), p=p)

    def test_invalid_probability_types_are_rejected_by_cic(self) -> None:
        for p in (True, None, "0.5", complex(0.5, 0)):
            with self.subTest(p=p):
                with self.assertRaisesRegex(TypeError, "real number"):
                    evaluate(nx.path_graph(5), p=p)

    def test_overlapping_seeds_are_rejected_by_cic(self) -> None:
        with self.assertRaisesRegex(ValueError, "disjoint"):
            evaluate(nx.path_graph(5), [0], [0])

    def test_missing_seeds_are_rejected_by_cic(self) -> None:
        for rumor, protector in (([99], [3]), ([0], [99])):
            with self.subTest(rumor=rumor, protector=protector):
                with self.assertRaisesRegex(ValueError, "do not exist"):
                    evaluate(nx.path_graph(5), rumor, protector)

    def test_unknown_tie_rule_is_rejected_by_cic(self) -> None:
        with self.assertRaisesRegex(ValueError, "tie_breaking"):
            evaluate(nx.path_graph(5), rule="first-visited")

    def test_invalid_tie_rule_type_is_rejected_by_cic(self) -> None:
        for rule in (True, None, 1):
            with self.subTest(rule=rule):
                with self.assertRaisesRegex(TypeError, "tie_breaking"):
                    evaluate(nx.path_graph(5), rule=rule)

    def test_unsupported_node_labels_are_rejected_by_cic(self) -> None:
        graph = nx.path_graph(5)
        graph.add_node(object())
        with self.assertRaisesRegex(TypeError, "CIC node labels"):
            evaluate(graph)

    def test_base_seed_and_tie_rule_must_be_supplied_explicitly(self) -> None:
        for keywords in ({"base_random_seed": 42}, {"tie_breaking": "protector-priority"}, {}):
            with self.subTest(keywords=keywords):
                with self.assertRaises(TypeError):
                    evaluate_cic(nx.path_graph(5), [0], [3], 0.5, 2, **keywords)

    def test_cic_failures_propagate_instead_of_returning_partial_statistics(self) -> None:
        failure = RuntimeError("test simulation failure")
        with patch("src.evaluation.monte_carlo.simulate_cic", side_effect=failure) as cic:
            with self.assertRaises(RuntimeError) as context:
                evaluate(nx.path_graph(5), simulations=5)
        self.assertIs(context.exception, failure)
        self.assertEqual(cic.call_count, 1)


class ProcessedDatasetMonteCarloTests(unittest.TestCase):
    def test_p_zero_on_all_three_processed_datasets(self) -> None:
        for name in DATASETS:
            with self.subTest(dataset=name):
                graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
                result = evaluate(graph, [min(graph)], [max(graph)], p=0, simulations=2)
                self.assertEqual(result.mean_rumor_count, 1)
                self.assertEqual(result.mean_protector_count, 1)
                self.assertEqual(result.mean_inactive_count, len(graph) - 2)
                self.assertEqual(result.std_rumor_count, 0)

    def test_email_raw_observations_match_direct_cic(self) -> None:
        graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
        result = evaluate(graph, [0], [1], p=0.05, simulations=3)
        for run in result.raw_results:
            direct = simulate_cic(graph, [0], [1], 0.05,
                                  tie_breaking="protector-priority", random_seed=run.random_seed)
            self.assertEqual(run.rumor_count, direct.rumor_count)
            self.assertEqual(run.protector_count, direct.protector_count)
            self.assertEqual(run.inactive_count, direct.inactive_count)
        self.assertAlmostEqual(
            result.mean_rumor_count + result.mean_protector_count + result.mean_inactive_count, 1005,
        )
