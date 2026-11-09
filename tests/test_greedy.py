"""Full Greedy on hand-checkable graphs and explicit restricted variants."""

from copy import deepcopy
import random
import unittest
from unittest.mock import patch

import networkx as nx

from src.algorithms import (
    estimate_greedy_cost, select_candidate_restricted_greedy, select_greedy,
)
from src.evaluation import evaluate_cic


def full(graph, rumor=(0,), k=2, p=1, simulations=3, base=42, rule="protector-priority"):
    return select_greedy(graph, rumor, k, p, simulations, base_random_seed=base, tie_breaking=rule)


def restricted(graph, pool, rumor=(0,), k=2, p=1, simulations=3, base=42, rule="protector-priority"):
    return select_candidate_restricted_greedy(
        graph, rumor, k, p, simulations, candidate_nodes=pool,
        base_random_seed=base, tie_breaking=rule,
    )


class GreedyTests(unittest.TestCase):
    def test_zero_budget_returns_empty_without_evaluating_or_fabricating_score(self) -> None:
        with patch("src.algorithms.greedy.evaluate_cic", wraps=evaluate_cic) as evaluator:
            result = full(nx.path_graph(4), k=0)
        self.assertEqual(result.protector_nodes, frozenset())
        self.assertEqual(result.selection_order, ())
        self.assertEqual(result.steps, ())
        self.assertEqual((result.evaluation_count, result.cic_simulation_count), (0, 0))
        self.assertIsNone(result.final_mean_rumor_count)
        self.assertEqual(evaluator.call_count, 0)

    def test_restricted_empty_pool_with_zero_budget_is_valid(self) -> None:
        result = restricted(nx.Graph(), [], rumor=[], k=0)
        self.assertEqual(result.protector_nodes, frozenset())
        self.assertEqual(result.evaluation_count, 0)
        self.assertEqual(result.algorithm, "candidate-restricted-greedy")

    def test_exact_work_formula_including_empty_and_all_node_budgets(self) -> None:
        for m, k, simulations, evaluations in ((0, 0, 1, 0), (3, 0, 4, 0), (3, 2, 4, 5), (3, 3, 2, 6), (1004, 5, 500, 5010)):
            with self.subTest(m=m, k=k):
                cost = estimate_greedy_cost(m, k, simulations)
                self.assertEqual(cost.evaluation_count, evaluations)
                self.assertEqual(cost.cic_simulation_count, evaluations * simulations)

    def test_invalid_work_estimates_are_rejected(self) -> None:
        for args in ((-1, 0, 1), (2, -1, 1), (2, 3, 1), (2, 1, 0), (True, 1, 1), (2, True, 1), (2, 1, 1.5)):
            with self.subTest(args=args), self.assertRaises((TypeError, ValueError)):
                estimate_greedy_cost(*args)

    def test_directed_chain_has_known_full_greedy_history(self) -> None:
        result = full(nx.DiGraph([(0, 1), (1, 2), (2, 3)]), simulations=4)
        self.assertEqual(result.algorithm, "full-greedy")
        self.assertEqual(result.selection_order, (1, 2))
        self.assertEqual(result.protector_nodes, {1, 2})
        self.assertEqual([step.mean_rumor_count for step in result.steps], [1, 1])
        self.assertEqual([step.protector_nodes for step in result.steps], [{1}, {1, 2}])
        self.assertEqual([step.evaluation_count for step in result.steps], [3, 2])
        self.assertEqual((result.evaluation_count, result.cic_simulation_count), (5, 20))
        self.assertEqual({trial.candidate_node: trial.mean_rumor_count for trial in result.steps[0].candidate_evaluations}, {1: 1, 2: 2, 3: 3})

    def test_undirected_chain_respects_deterministic_ties(self) -> None:
        result = full(nx.path_graph(4))
        self.assertEqual(result.selection_order, (1, 2))
        self.assertEqual(result.final_mean_rumor_count, 1)

    def test_each_choice_is_recomputed_after_previous_choice(self) -> None:
        graph = nx.DiGraph([(0, 10), (10, 1), (1, 2), (0, 20), (20, 30)])
        result = full(graph)
        # Independent singleton ranking would tie node 1 with node 20 and take
        # node 1 second. Re-evaluating P={10,v} must instead choose node 20.
        self.assertEqual(result.selection_order, (10, 20))
        self.assertEqual([step.mean_rumor_count for step in result.steps], [3, 1])
        self.assertEqual(result.evaluation_count, 9)

    def test_every_remaining_candidate_is_evaluated_with_the_current_P(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        with patch("src.algorithms.greedy.evaluate_cic", wraps=evaluate_cic) as evaluator:
            result = full(graph, base=100)
        self.assertEqual(evaluator.call_count, 5)
        self.assertEqual([call.args[2] for call in evaluator.call_args_list],
                         [{1}, {2}, {3}, {1, 2}, {1, 3}])
        for call in evaluator.call_args_list:
            self.assertIs(call.args[0], graph)
            self.assertEqual(call.args[1], {0})
            self.assertEqual(call.args[3:], (1, 3))
            self.assertEqual(call.kwargs, {"base_random_seed": 100, "tie_breaking": "protector-priority"})
        self.assertEqual(result.evaluation_count, evaluator.call_count)

    def test_full_greedy_does_not_drop_isolates_or_low_degree_candidates(self) -> None:
        graph = nx.DiGraph([(0, 1)])
        graph.add_nodes_from([90, 8000])
        result = full(graph, k=1)
        self.assertEqual(result.candidate_nodes, {1, 90, 8000})
        self.assertEqual([trial.candidate_node for trial in result.steps[0].candidate_evaluations], [1, 90, 8000])

    def test_sparse_ids_and_rumor_exclusion(self) -> None:
        graph = nx.DiGraph([(3, 17), (17, 90), (90, 8000)])
        result = full(graph, rumor=[3])
        self.assertEqual(result.selection_order, (17, 90))
        self.assertNotIn(3, result.protector_nodes)
        for step in result.steps:
            self.assertNotIn(3, {trial.candidate_node for trial in step.candidate_evaluations})

    def test_valid_budget_can_select_all_eligible_nodes(self) -> None:
        result = full(nx.path_graph(4), k=3)
        self.assertEqual(result.protector_nodes, {1, 2, 3})
        self.assertEqual(result.evaluation_count, 6)

    def test_flat_objective_still_selects_exactly_k(self) -> None:
        graph = nx.Graph()
        graph.add_nodes_from([9000, 100, 3, 17])
        result = full(graph, rumor=[9000], p=0)
        self.assertEqual(result.selection_order, (3, 17))
        self.assertEqual(result.evaluation_count, 5)

    def test_oversized_budget_is_rejected_for_full_greedy(self) -> None:
        with self.assertRaises(ValueError):
            full(nx.path_graph(4), k=4)

    def test_oversized_budget_is_checked_against_the_restricted_pool(self) -> None:
        with self.assertRaisesRegex(ValueError, "candidate_count"):
            restricted(nx.path_graph(10), [1, 2], k=3)

    def test_restricted_pool_is_explicit_and_changes_the_search_space(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        complete = full(graph, k=1)
        limited = restricted(graph, [2, 3], k=1)
        self.assertEqual(complete.protector_nodes, {1})
        self.assertEqual(limited.protector_nodes, {2})
        self.assertEqual(limited.candidate_nodes, {2, 3})
        self.assertEqual(limited.algorithm, "candidate-restricted-greedy")
        self.assertEqual(limited.evaluation_count, 2)

    def test_restricted_pool_equal_to_full_pool_matches_full_history(self) -> None:
        graph = nx.gnp_random_graph(7, 0.3, seed=7, directed=True)
        complete = full(graph, p=0.4)
        limited = restricted(graph, [6, 5, 4, 3, 2, 1], p=0.4)
        self.assertEqual(complete.steps, limited.steps)
        self.assertEqual(complete.selection_order, limited.selection_order)
        self.assertNotEqual(complete.algorithm, limited.algorithm)

    def test_unknown_or_rumor_candidate_is_rejected(self) -> None:
        for pool in ([0, 1], [1, 99]):
            with self.subTest(pool=pool), self.assertRaises(ValueError):
                restricted(nx.path_graph(4), pool, k=1)

    def test_generator_inputs_are_materialized_once_and_deduplicated(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        limited = restricted(graph, iter([3, 2, 1, 1]), rumor=iter([0, 0]))
        self.assertEqual(limited.selection_order, (1, 2))
        self.assertEqual(limited.evaluation_count, 5)

    def test_unknown_rumor_seed_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exist"):
            full(nx.path_graph(4), rumor=[99])

    def test_invalid_budgets_and_graph_types_are_rejected(self) -> None:
        for k in (-1, True, 1.5):
            with self.assertRaises((TypeError, ValueError)):
                full(nx.path_graph(4), k=k)
        for graph in (None, [], nx.MultiGraph(), nx.MultiDiGraph()):
            with self.assertRaises(TypeError):
                full(graph, k=0)

    def test_model_settings_are_validated_even_with_zero_budget(self) -> None:
        for kwargs in ({"p": True}, {"p": -1}, {"p": float("nan")},
                       {"simulations": 0}, {"simulations": True}, {"base": -1}, {"base": None},
                       {"rule": "first-visited"}, {"rule": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                full(nx.path_graph(4), k=0, **kwargs)

    def test_stochastic_run_reproduces_every_selection_and_trial_score(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=7, directed=True)
        self.assertEqual(full(graph, p=0.4), full(graph, p=0.4))

    def test_order_of_graph_seeds_and_pool_does_not_change_results(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=13, directed=True)
        reverse = nx.DiGraph()
        reverse.add_nodes_from(reversed(list(graph)))
        reverse.add_edges_from(reversed(list(graph.edges())))
        self.assertEqual(full(graph, rumor=[0, 7], p=0.4), full(reverse, rumor=iter([7, 0]), p=0.4))
        self.assertEqual(restricted(graph, [1, 2, 3], p=0.4), restricted(reverse, [3, 2, 1], p=0.4))

    def test_each_step_matches_an_independent_exhaustive_next_step_oracle(self) -> None:
        graph = nx.gnp_random_graph(6, 0.3, seed=7, directed=True)
        result = full(graph, p=0.45)
        selected = set()
        for step in result.steps:
            scores = {v: evaluate_cic(graph, [0], selected | {v}, 0.45, 3,
                                      base_random_seed=42, tie_breaking="protector-priority").mean_rumor_count
                      for v in sorted(set(graph) - selected - {0})}
            expected = min(scores, key=lambda node: (scores[node], node))
            self.assertEqual(step.selected_node, expected)
            self.assertEqual(step.mean_rumor_count, scores[expected])
            selected.add(expected)

    def test_graph_attributes_and_input_collections_are_unchanged(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        graph.graph["name"] = "input"
        graph.nodes[2]["state"] = "inactive"
        graph.edges[1, 2]["weight"] = 0
        original = deepcopy(graph)
        rumor, pool = [0, 0], [1, 2, 3]
        restricted(nx.freeze(graph), pool, rumor=rumor)
        self.assertTrue(nx.utils.graphs_equal(graph, original))
        self.assertEqual(rumor, [0, 0])
        self.assertEqual(pool, [1, 2, 3])

    def test_global_random_state_is_unchanged(self) -> None:
        state = random.getstate()
        full(nx.path_graph(4), p=0.4)
        self.assertEqual(state, random.getstate())

    def test_wall_time_and_evaluator_time_are_recorded_separately(self) -> None:
        with patch("src.algorithms.greedy.perf_counter", side_effect=[10, 10.5]):
            result = full(nx.path_graph(4))
        self.assertEqual(result.runtime_seconds, 0.5)
        self.assertGreaterEqual(result.evaluation_runtime_seconds, 0)
        self.assertAlmostEqual(result.evaluation_runtime_seconds,
                               sum(trial.evaluation_runtime_seconds for step in result.steps for trial in step.candidate_evaluations))

    def test_evaluator_failure_is_not_hidden_by_partial_results(self) -> None:
        error = RuntimeError("test evaluator failure")
        with patch("src.algorithms.greedy.evaluate_cic", side_effect=error) as evaluator:
            with self.assertRaises(RuntimeError) as context:
                full(nx.path_graph(4))
        self.assertIs(context.exception, error)
        self.assertEqual(evaluator.call_count, 1)

    def test_empty_graph_and_empty_rumor_are_valid_at_zero_budget(self) -> None:
        result = full(nx.Graph(), rumor=[], k=0)
        self.assertEqual(result.candidate_nodes, frozenset())
        self.assertEqual(result.runtime_seconds >= 0, True)

    def test_string_labels_use_canonical_tie_order(self) -> None:
        graph = nx.Graph()
        graph.add_nodes_from(["z", "a", "r", "b"])
        result = full(graph, rumor=["r"], p=0)
        self.assertEqual(result.selection_order, ("a", "b"))
