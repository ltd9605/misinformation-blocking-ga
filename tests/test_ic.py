"""IC rules on hand-checkable graphs and processed SNAP datasets."""

from copy import deepcopy
import random
import unittest
from unittest.mock import patch

import networkx as nx

from src.data import load_processed_graph
from src.data.specs import DATASETS, PROJECT_ROOT
from src.diffusion import simulate_ic


class ICTests(unittest.TestCase):
    def test_p_zero_keeps_only_seeds(self) -> None:
        graph = nx.path_graph(5)
        result = simulate_ic(graph, [0, 3], 0, random_seed=42)
        self.assertEqual(result.active_nodes, {0, 3})
        self.assertEqual(result.active_count, 2)
        self.assertEqual(result.activation_layers, (frozenset({0, 3}),))
        self.assertEqual(result.steps, 0)

    def test_p_one_reaches_exactly_the_reachable_component(self) -> None:
        graph = nx.DiGraph([(0, 1), (0, 2), (2, 3), (90, 91)])
        graph.add_node(8000)
        result = simulate_ic(graph, [0], 1, random_seed=42)
        self.assertEqual(result.active_nodes, {0, 1, 2, 3})
        self.assertEqual(result.active_count, 4)
        self.assertEqual(result.steps, 2)

    def test_directed_chain_obeys_edge_direction_and_rounds(self) -> None:
        graph = nx.DiGraph([(3, 19), (19, 93)])
        for seed, expected in (
            (3, ({3}, {19}, {93})),
            (19, ({19}, {93})),
            (93, ({93},)),
        ):
            with self.subTest(seed=seed):
                result = simulate_ic(graph, [seed], 1, random_seed=7)
                self.assertEqual(result.activation_layers, tuple(map(frozenset, expected)))
                self.assertEqual(result.steps, len(expected) - 1)

    def test_undirected_chain_spreads_in_both_directions(self) -> None:
        graph = nx.Graph([(3, 19), (19, 93)])
        for seed, expected in (
            (3, ({3}, {19}, {93})),
            (19, ({19}, {3, 93})),
            (93, ({93}, {19}, {3})),
        ):
            with self.subTest(seed=seed):
                result = simulate_ic(graph, [seed], 1, random_seed=7)
                self.assertEqual(result.active_nodes, {3, 19, 93})
                self.assertEqual(result.activation_layers, tuple(map(frozenset, expected)))

    def test_isolated_seed_stays_active_without_spreading(self) -> None:
        graph = nx.DiGraph([(0, 1)])
        graph.add_node(8000)
        result = simulate_ic(graph, [8000], 1, random_seed=42)
        self.assertEqual(result.active_nodes, {8000})
        self.assertEqual(result.active_count, 1)
        self.assertEqual(result.steps, 0)

    def test_missing_seed_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not exist"):
            simulate_ic(nx.path_graph(3), [0, 8000], 0.5, random_seed=42)

    def test_same_random_seed_reproduces_every_result_field(self) -> None:
        graph = nx.gnp_random_graph(30, 0.2, seed=13, directed=True)
        first = simulate_ic(graph, [0, 3], 0.25, random_seed=42)
        self.assertEqual(first, simulate_ic(graph, [0, 3], 0.25, random_seed=42))
        self.assertGreater(first.active_count, 2)
        self.assertLess(first.active_count, len(graph))

    def test_cycles_self_loops_and_converging_paths_never_reactivate_nodes(self) -> None:
        graph = nx.DiGraph([(0, 1), (0, 2), (1, 3), (2, 3), (3, 0), (3, 3)])
        with patch("src.diffusion.ic.Random") as random_type:
            random_type.return_value.random.return_value = 0.1
            result = simulate_ic(graph, [0], 0.5, random_seed=42)
        flattened = [node for layer in result.activation_layers for node in layer]
        self.assertEqual(result.active_nodes, {0, 1, 2, 3})
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(result.activation_layers, (frozenset({0}), frozenset({1, 2}), frozenset({3})))
        self.assertEqual(random_type.return_value.random.call_count, 3)

    def test_failed_edge_is_not_retried_in_later_rounds(self) -> None:
        graph = nx.DiGraph([(0, 1), (0, 2), (2, 3)])
        with patch("src.diffusion.ic.Random") as random_type:
            random_type.return_value.random.side_effect = [0.9, 0.1, 0.1]
            result = simulate_ic(graph, [0], 0.5, random_seed=42)
        self.assertEqual(result.active_nodes, {0, 2, 3})
        self.assertEqual(result.steps, 2)
        self.assertEqual(random_type.return_value.random.call_count, 3)

    def test_failed_parent_does_not_block_another_parents_attempt(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        with patch("src.diffusion.ic.Random") as random_type:
            random_type.return_value.random.side_effect = [0.9, 0.1, 0.1]
            result = simulate_ic(graph, [0, 1], 0.5, random_seed=42)
        self.assertEqual(result.activation_layers, (frozenset({0, 1}), frozenset({2}), frozenset({3})))
        self.assertEqual(random_type.return_value.random.call_count, 3)

    def test_attempt_at_probability_threshold_fails(self) -> None:
        with patch("src.diffusion.ic.Random") as random_type:
            random_type.return_value.random.return_value = 0.5
            result = simulate_ic(nx.path_graph(2), [0], 0.5, random_seed=42)
        self.assertEqual(result.active_nodes, {0})

    def test_newly_active_nodes_wait_until_the_next_round(self) -> None:
        graph = nx.DiGraph([(0, 1), (0, 2), (1, 3), (3, 4), (2, 4)])
        result = simulate_ic(graph, [0], 1, random_seed=42)
        self.assertEqual(result.activation_layers, (frozenset({0}), frozenset({1, 2}), frozenset({3, 4})))
        self.assertEqual(result.steps, 2)

    def test_empty_seeds_produce_no_activity(self) -> None:
        result = simulate_ic(nx.path_graph(3), [], 1, random_seed=42)
        self.assertEqual(result.active_nodes, frozenset())
        self.assertEqual(result.active_count, 0)
        self.assertEqual(result.activation_layers, ())
        self.assertEqual(result.steps, 0)

    def test_empty_graph_with_empty_seeds_terminates(self) -> None:
        result = simulate_ic(nx.DiGraph(), [], 0.5, random_seed=42)
        self.assertEqual((result.active_count, result.steps), (0, 0))

    def test_duplicate_seeds_are_deduplicated_without_changing_input(self) -> None:
        seeds = [0, 0, 1]
        result = simulate_ic(nx.path_graph(3), seeds, 0, random_seed=42)
        self.assertEqual(result.active_nodes, {0, 1})
        self.assertEqual(result.active_count, 2)
        self.assertEqual(seeds, [0, 0, 1])

    def test_invalid_probability_values_are_rejected(self) -> None:
        for probability in (-0.01, 1.01, float("nan"), float("inf"), -float("inf")):
            with self.subTest(probability=probability):
                with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
                    simulate_ic(nx.path_graph(2), [0], probability, random_seed=42)

    def test_invalid_probability_types_are_rejected(self) -> None:
        for probability in (None, "0.5", True, complex(0.5, 0)):
            with self.subTest(probability=probability):
                with self.assertRaisesRegex(TypeError, "real number"):
                    simulate_ic(nx.path_graph(2), [0], probability, random_seed=42)

    def test_invalid_random_seed_types_are_rejected(self) -> None:
        for seed in (True, 1.5, "42"):
            with self.subTest(seed=seed):
                with self.assertRaisesRegex(TypeError, "integer or None"):
                    simulate_ic(nx.path_graph(2), [0], 0.5, random_seed=seed)

    def test_unsupported_graph_types_are_rejected(self) -> None:
        for graph in (None, [(0, 1)], nx.MultiGraph([(0, 1)]), nx.MultiDiGraph([(0, 1)])):
            with self.subTest(graph=type(graph)):
                with self.assertRaisesRegex(TypeError, "simple NetworkX"):
                    simulate_ic(graph, [0], 0.5, random_seed=42)

    def test_graph_topology_and_attributes_are_unchanged(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 0), (1, 2)])
        graph.graph["label"] = "input"
        graph.nodes[0]["active"] = False
        graph.edges[0, 1]["weight"] = 0
        before = deepcopy(graph)
        result = simulate_ic(graph, [0], 1, random_seed=42)
        self.assertTrue(nx.utils.graphs_equal(before, graph))
        self.assertEqual(result.active_nodes, {0, 1, 2})

    def test_global_rng_state_is_unchanged(self) -> None:
        before = random.getstate()
        simulate_ic(nx.path_graph(5), [0], 0.5, random_seed=42)
        self.assertEqual(random.getstate(), before)

    def test_seed_input_order_does_not_change_random_outcomes(self) -> None:
        graph = nx.complete_graph(10, create_using=nx.DiGraph)
        first = simulate_ic(graph, [0, 3], 0.2, random_seed=7)
        second = simulate_ic(graph, iter([3, 0, 3]), 0.2, random_seed=7)
        self.assertEqual(first, second)

    def test_edge_insertion_order_does_not_change_random_outcomes(self) -> None:
        edges = [(0, 2), (0, 1), (1, 3), (2, 4), (3, 4)]
        first = nx.DiGraph()
        second = nx.DiGraph()
        first.add_nodes_from(range(5))
        second.add_nodes_from(range(5))
        first.add_edges_from(edges)
        second.add_edges_from(reversed(edges))
        self.assertEqual(
            simulate_ic(first, [0], 0.5, random_seed=42),
            simulate_ic(second, [0], 0.5, random_seed=42),
        )

    def test_hashable_labels_need_not_be_mutually_sortable(self) -> None:
        graph = nx.Graph([("seed", 8000), (8000, ("target", 1))])
        result = simulate_ic(graph, ["seed"], 1, random_seed=42)
        self.assertEqual(result.active_nodes, {"seed", 8000, ("target", 1)})
        self.assertEqual(result.steps, 2)

    def test_random_seed_is_optional(self) -> None:
        result = simulate_ic(nx.path_graph(3), [0], 1)
        self.assertEqual(result.active_nodes, {0, 1, 2})


class ProcessedDatasetICTests(unittest.TestCase):
    def test_p_zero_on_all_processed_datasets(self) -> None:
        for name in DATASETS:
            with self.subTest(dataset=name):
                graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
                seed = max(graph)
                result = simulate_ic(graph, [seed], 0, random_seed=42)
                self.assertEqual(result.active_nodes, {seed})
                self.assertEqual(result.steps, 0)

    def test_p_one_on_all_processed_datasets_matches_independent_reachability(self) -> None:
        for name in DATASETS:
            with self.subTest(dataset=name):
                graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
                seed = min(graph)
                expected = (
                    nx.descendants(graph, seed) | {seed} if graph.is_directed()
                    else set(nx.node_connected_component(graph, seed))
                )
                result = simulate_ic(nx.freeze(graph), [seed], 1, random_seed=42)
                self.assertEqual(result.active_nodes, expected)
                self.assertEqual(result.active_count, len(expected))

    def test_email_processed_isolate_remains_a_single_active_seed(self) -> None:
        graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
        seed = min(nx.isolates(graph))
        result = simulate_ic(graph, [seed], 1, random_seed=42)
        self.assertEqual(result.active_nodes, {seed})
        self.assertEqual(result.steps, 0)
