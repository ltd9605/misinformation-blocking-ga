"""Selection invariants, ranking rules and CIC evaluator integration."""

from copy import deepcopy
import random
import unittest
from unittest.mock import patch

import networkx as nx

from src.algorithms import select_degree, select_pagerank, select_random
from src.data import load_processed_graph
from src.data.specs import DATASETS, PROJECT_ROOT
from src.evaluation import evaluate_cic


METHODS = (select_random, select_degree, select_pagerank)


class BaselineTests(unittest.TestCase):
    def test_all_methods_return_exactly_k_distinct_nonrumor_sparse_ids(self) -> None:
        graph = nx.DiGraph([(3, 90), (90, 8000), (17, 90)])
        graph.add_node(60000)
        for method in METHODS:
            with self.subTest(method=method.__name__):
                result = method(graph, [90], 3)
                self.assertIsInstance(result, frozenset)
                self.assertEqual(len(result), 3)
                self.assertTrue(result <= set(graph))
                self.assertFalse(result & {90})

    def test_zero_budget_is_valid_for_all_methods(self) -> None:
        for graph, rumor in ((nx.Graph(), []), (nx.path_graph(3), [0, 1, 2])):
            for method in METHODS:
                with self.subTest(method=method.__name__, nodes=len(graph)):
                    self.assertEqual(method(graph, rumor, 0), frozenset())

    def test_budget_can_equal_all_eligible_nodes(self) -> None:
        for method in METHODS:
            self.assertEqual(method(nx.path_graph(4), [0], 3), {1, 2, 3})

    def test_unknown_rumor_seed_is_rejected(self) -> None:
        for method in METHODS:
            with self.assertRaisesRegex(ValueError, "exist"):
                method(nx.path_graph(3), [99], 1)

    def test_negative_or_oversized_budget_is_rejected(self) -> None:
        for method in METHODS:
            for k in (-1, 3):
                with self.subTest(method=method.__name__, k=k):
                    with self.assertRaises(ValueError):
                        method(nx.path_graph(3), [0], k)

    def test_invalid_budget_type_is_rejected(self) -> None:
        for method in METHODS:
            for k in (True, 1.5, "1", None):
                with self.subTest(method=method.__name__, k=k):
                    with self.assertRaises(TypeError):
                        method(nx.path_graph(3), [0], k)

    def test_unsupported_graphs_are_rejected(self) -> None:
        for method in METHODS:
            for graph in (None, [], nx.MultiGraph(), nx.MultiDiGraph()):
                with self.assertRaisesRegex(TypeError, "simple NetworkX"):
                    method(graph, [], 0)

    def test_generator_and_duplicate_rumor_seeds_are_supported(self) -> None:
        for method in METHODS:
            self.assertEqual(method(nx.path_graph(3), iter([0, 0]), 2), {1, 2})

    def test_inputs_are_not_modified(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        graph.graph["name"] = "input"
        graph.nodes[2]["state"] = "inactive"
        graph.edges[0, 2]["weight"] = 999
        before = deepcopy(graph)
        rumor = [0, 0]
        for method in METHODS:
            method(nx.freeze(graph), rumor, 2)
            self.assertTrue(nx.utils.graphs_equal(graph, before))
            self.assertEqual(rumor, [0, 0])

    def test_random_selection_replays_from_canonical_candidates(self) -> None:
        graph = nx.Graph()
        graph.add_nodes_from([8000, 90, 17, 3])
        expected = frozenset(random.Random(7).sample([3, 90, 8000], 2))
        self.assertEqual(select_random(graph, [17], 2, random_seed=7), expected)
        self.assertEqual(select_random(graph, [17], 2, random_seed=7), expected)

    def test_random_selection_does_not_use_global_rng(self) -> None:
        state = random.getstate()
        select_random(nx.path_graph(5), [0], 2, random_seed=42)
        self.assertEqual(state, random.getstate())

    def test_random_seed_type_is_validated(self) -> None:
        for seed in (True, 1.5, "42"):
            with self.assertRaisesRegex(TypeError, "random_seed"):
                select_random(nx.path_graph(4), [0], 2, random_seed=seed)

    def test_directed_degree_uses_outgoing_not_incoming_edges(self) -> None:
        graph = nx.DiGraph([(3, 90), (3, 17), (3, 8000), (17, 90), (8000, 90)])
        self.assertEqual(select_degree(graph, [], 1), {3})
        self.assertEqual(select_degree(graph, [3], 2), {17, 8000})

    def test_undirected_degree_selects_the_center(self) -> None:
        graph = nx.Graph([(90, 3), (90, 17), (90, 8000)])
        self.assertEqual(select_degree(graph, [], 1), {90})

    def test_equal_degree_uses_numeric_id_order(self) -> None:
        graph = nx.cycle_graph([9000, 100, 3, 17])
        self.assertEqual(select_degree(graph, [], 2), {3, 17})

    def test_degree_ignores_edge_weights(self) -> None:
        graph = nx.DiGraph()
        graph.add_weighted_edges_from([(0, 3, 100), (1, 2, 1), (1, 3, 1)])
        self.assertEqual(select_degree(graph, [], 1), {1})

    def test_pagerank_uses_incoming_structure(self) -> None:
        graph = nx.DiGraph([(3, 90)])
        self.assertEqual(select_pagerank(graph, [], 1), {90})

    def test_pagerank_filters_rumor_after_scoring_the_entire_graph(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        with patch("src.algorithms.baselines.nx.pagerank", wraps=nx.pagerank) as pagerank:
            result = select_pagerank(graph, [2], 1)
        self.assertNotIn(2, result)
        scored_graph = pagerank.call_args.args[0]
        self.assertEqual(set(scored_graph), set(graph))
        self.assertEqual(set(scored_graph.edges()), set(graph.edges()))
        self.assertIsNot(scored_graph, graph)
        self.assertIsNone(pagerank.call_args.kwargs["weight"])

    def test_equal_pagerank_scores_use_ascending_id(self) -> None:
        graph = nx.Graph()
        graph.add_nodes_from([9000, 17, 3, 100])
        self.assertEqual(select_pagerank(graph, [], 2), {3, 17})

    def test_pagerank_undirected_graph_selects_star_center(self) -> None:
        self.assertEqual(select_pagerank(nx.star_graph(4), [], 1), {0})

    def test_pagerank_ignores_edge_weights(self) -> None:
        graph = nx.DiGraph([(0, 1), (0, 2), (1, 0), (2, 0)])
        graph.edges[0, 1]["weight"] = 1e12
        graph.edges[0, 2]["weight"] = 0
        self.assertEqual(select_pagerank(graph, [0], 1), {1})

    def test_pagerank_convergence_error_is_not_hidden(self) -> None:
        with self.assertRaises(nx.PowerIterationFailedConvergence):
            select_pagerank(nx.path_graph(4), [], 1, max_iter=1)

    def test_pagerank_configuration_validation(self) -> None:
        invalid = (
            {"alpha": True}, {"alpha": -0.1}, {"alpha": 1}, {"alpha": float("nan")},
            {"tol": 0}, {"tol": float("inf")}, {"tol": "1e-6"},
            {"max_iter": True}, {"max_iter": 0}, {"max_iter": 1.5},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                select_pagerank(nx.path_graph(4), [], 1, **kwargs)

    def test_insertion_order_does_not_change_any_baseline(self) -> None:
        graph = nx.gnp_random_graph(20, 0.2, seed=7, directed=True)
        reverse = nx.DiGraph()
        reverse.add_nodes_from(reversed(list(graph)))
        reverse.add_edges_from(reversed(list(graph.edges())))
        self.assertEqual(select_random(graph, [0], 5, random_seed=7), select_random(reverse, [0], 5, random_seed=7))
        self.assertEqual(select_degree(graph, [0], 5), select_degree(reverse, [0], 5))
        self.assertEqual(select_pagerank(graph, [0], 5), select_pagerank(reverse, [0], 5))

    def test_supported_string_labels_work(self) -> None:
        graph = nx.Graph([("center", "a"), ("center", "z")])
        for method in METHODS:
            result = method(graph, ["z"], 2)
            self.assertEqual(result, {"a", "center"})


class ProcessedBaselineTests(unittest.TestCase):
    def test_all_baselines_integrate_with_evaluate_cic_on_all_datasets(self) -> None:
        for name in DATASETS:
            graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
            rumor = [min(graph)]
            for method in METHODS:
                with self.subTest(dataset=name, method=method.__name__):
                    protector = method(graph, rumor, 3)
                    self.assertEqual(len(protector), 3)
                    self.assertFalse(protector & set(rumor))
                    result = evaluate_cic(graph, rumor, protector, 0, 2,
                                          base_random_seed=42, tie_breaking="protector-priority")
                    self.assertEqual(result.mean_protector_count, 3)
                    self.assertEqual(result.mean_rumor_count, 1)
