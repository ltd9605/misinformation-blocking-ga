"""CIC timing, competition, reproducibility and processed-data integration."""

from copy import deepcopy
import json
import os
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

import networkx as nx

from src.data import load_processed_graph
from src.data.specs import DATASETS, PROJECT_ROOT
from src.diffusion import CICLayer, CICResult, TieBreakingRule, simulate_cic, simulate_ic


def run_cic(graph, rumor, protector, p=1, rule="protector-priority", seed=42) -> CICResult:
    """Keep each test's model configuration explicit at the simulator boundary."""
    return simulate_cic(graph, rumor, protector, p, tie_breaking=rule, random_seed=seed)


class CICAssertions(unittest.TestCase):
    def assert_partition(self, graph: nx.Graph, result: CICResult) -> None:
        """Check state permanence, unique activation and conservation of nodes."""
        self.assertFalse(result.rumor_nodes & result.protector_nodes)
        self.assertFalse(result.rumor_nodes & result.inactive_nodes)
        self.assertFalse(result.protector_nodes & result.inactive_nodes)
        self.assertEqual(result.rumor_nodes | result.protector_nodes | result.inactive_nodes, set(graph))
        self.assertEqual(result.rumor_count + result.protector_count + result.inactive_count, len(graph))
        seen = set()
        rumor = set()
        protector = set()
        for layer in result.activation_layers:
            self.assertFalse(layer.rumor_nodes & layer.protector_nodes)
            newly_active = layer.rumor_nodes | layer.protector_nodes
            self.assertTrue(newly_active)
            self.assertFalse(seen & newly_active)
            seen.update(newly_active)
            rumor.update(layer.rumor_nodes)
            protector.update(layer.protector_nodes)
        self.assertEqual(rumor, result.rumor_nodes)
        self.assertEqual(protector, result.protector_nodes)
        self.assertEqual(result.steps, max(0, len(result.activation_layers) - 1))


class CICTests(CICAssertions):
    def test_only_rumor_matches_ic_on_canonical_node_order(self) -> None:
        graph = nx.gnp_random_graph(20, 0.2, seed=7, directed=True)
        for p in (0, 0.3, 1):
            with self.subTest(p=p):
                ic = simulate_ic(graph, [0, 3], p, random_seed=42)
                cic = run_cic(graph, [0, 3], [], p)
                self.assertEqual(cic.rumor_nodes, ic.active_nodes)
                self.assertEqual(cic.protector_count, 0)
                self.assertEqual(tuple(layer.rumor_nodes for layer in cic.activation_layers), ic.activation_layers)
                self.assertEqual(cic.steps, ic.steps)
                self.assert_partition(graph, cic)

    def test_only_protector_matches_ic_on_canonical_node_order(self) -> None:
        graph = nx.gnp_random_graph(20, 0.2, seed=7, directed=True)
        for p in (0, 0.3, 1):
            with self.subTest(p=p):
                ic = simulate_ic(graph, [0, 3], p, random_seed=42)
                cic = run_cic(graph, [], [0, 3], p)
                self.assertEqual(cic.protector_nodes, ic.active_nodes)
                self.assertEqual(cic.rumor_count, 0)
                self.assertEqual(tuple(layer.protector_nodes for layer in cic.activation_layers), ic.activation_layers)
                self.assertEqual(cic.steps, ic.steps)
                self.assert_partition(graph, cic)

    def test_both_seed_sets_empty_leave_all_nodes_inactive(self) -> None:
        graph = nx.path_graph(4)
        result = run_cic(graph, [], [])
        self.assertEqual(result.inactive_nodes, {0, 1, 2, 3})
        self.assertEqual(result.activation_layers, ())
        self.assertEqual(result.steps, 0)
        self.assert_partition(graph, result)

    def test_empty_graph_with_empty_seeds_terminates(self) -> None:
        result = run_cic(nx.DiGraph(), [], [])
        self.assertEqual((result.rumor_count, result.protector_count, result.inactive_count, result.steps), (0, 0, 0, 0))

    def test_cascades_in_separate_components_do_not_interfere(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (3, 4), (4, 5)])
        graph.add_node(99)
        result = run_cic(graph, [0], [3])
        self.assertEqual(result.rumor_nodes, {0, 1, 2})
        self.assertEqual(result.protector_nodes, {3, 4, 5})
        self.assertEqual(result.inactive_nodes, {99})
        self.assertEqual(result.steps, 2)
        self.assert_partition(graph, result)

    def test_rumor_arriving_first_keeps_state_despite_protector_priority(self) -> None:
        graph = nx.DiGraph([(0, 3), (9, 8), (8, 3), (3, 4)])
        result = run_cic(graph, [0], [9])
        self.assertEqual(result.rumor_nodes, {0, 3, 4})
        self.assertEqual(result.protector_nodes, {9, 8})
        self.assert_partition(graph, result)

    def test_protector_arriving_first_keeps_state_despite_rumor_priority(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 3), (9, 3), (3, 4)])
        result = run_cic(graph, [0], [9], rule="rumor-priority")
        self.assertEqual(result.rumor_nodes, {0, 1})
        self.assertEqual(result.protector_nodes, {9, 3, 4})
        self.assert_partition(graph, result)

    def test_simultaneous_success_uses_protector_priority(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        result = run_cic(graph, [0], [1])
        self.assertEqual(result.rumor_nodes, {0})
        self.assertEqual(result.protector_nodes, {1, 2, 3})
        self.assertEqual(result.activation_layers, (
            CICLayer(frozenset({0}), frozenset({1})),
            CICLayer(frozenset(), frozenset({2})),
            CICLayer(frozenset(), frozenset({3})),
        ))
        self.assert_partition(graph, result)

    def test_simultaneous_success_uses_rumor_priority(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
        result = run_cic(graph, [0], [1], rule="rumor-priority")
        self.assertEqual(result.rumor_nodes, {0, 2, 3})
        self.assertEqual(result.protector_nodes, {1})
        self.assert_partition(graph, result)

    def test_tie_depends_on_success_not_just_simultaneous_attempts(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2)])
        for draws, rumor, protector in (
            ([0.1, 0.9], {0, 2}, {1}),
            ([0.9, 0.1], {0}, {1, 2}),
            ([0.9, 0.9], {0}, {1}),
            ([0.1, 0.1], {0}, {1, 2}),
        ):
            with self.subTest(draws=draws), patch("src.diffusion.cic.Random") as rng:
                rng.return_value.random.side_effect = draws
                result = run_cic(graph, [0], [1], 0.5)
                self.assertEqual(result.rumor_nodes, rumor)
                self.assertEqual(result.protector_nodes, protector)
                self.assertEqual(rng.return_value.random.call_count, 2)
                self.assert_partition(graph, result)

    def test_failed_parent_does_not_block_another_parent(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (9, 2)])
        with patch("src.diffusion.cic.Random") as rng:
            rng.return_value.random.side_effect = [0.9, 0.1, 0.9]
            result = run_cic(graph, [0, 1], [9], 0.5)
        self.assertEqual(result.rumor_nodes, {0, 1, 2})
        self.assertEqual(result.protector_nodes, {9})
        self.assertEqual(rng.return_value.random.call_count, 3)

    def test_same_cascade_success_does_not_suppress_competitor(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (9, 2)])
        with patch("src.diffusion.cic.Random") as rng:
            rng.return_value.random.side_effect = [0.1, 0.1]
            result = run_cic(graph, [0, 1], [9], 0.5)
        self.assertEqual(result.rumor_nodes, {0, 1})
        self.assertEqual(result.protector_nodes, {9, 2})
        self.assertEqual(rng.return_value.random.call_count, 2)

    def test_failed_edge_is_not_retried_later(self) -> None:
        graph = nx.DiGraph([(0, 2), (0, 3), (3, 4)])
        graph.add_node(9)
        with patch("src.diffusion.cic.Random") as rng:
            rng.return_value.random.side_effect = [0.9, 0.1, 0.1]
            result = run_cic(graph, [0], [9], 0.5)
        self.assertEqual(result.rumor_nodes, {0, 3, 4})
        self.assertEqual(result.inactive_nodes, {2})
        self.assertEqual(rng.return_value.random.call_count, 3)

    def test_attempt_at_probability_threshold_fails(self) -> None:
        with patch("src.diffusion.cic.Random") as rng:
            rng.return_value.random.return_value = 0.5
            result = run_cic(nx.DiGraph([(0, 2), (1, 2)]), [0], [1], 0.5)
        self.assertEqual(result.inactive_nodes, {2})

    def test_newly_active_node_cannot_transmit_in_its_activation_round(self) -> None:
        graph = nx.DiGraph([(0, 2), (2, 4), (1, 4)])
        result = run_cic(graph, [0], [1], rule="rumor-priority")
        self.assertEqual(result.rumor_nodes, {0, 2})
        self.assertEqual(result.protector_nodes, {1, 4})
        self.assertEqual(result.steps, 1)
        self.assert_partition(graph, result)

    def test_directed_graph_never_uses_incoming_edges(self) -> None:
        graph = nx.DiGraph([(0, 2), (2, 4), (1, 3), (3, 4)])
        result = run_cic(graph, [4], [1])
        self.assertEqual(result.rumor_nodes, {4})
        self.assertEqual(result.protector_nodes, {1, 3})
        self.assertEqual(result.inactive_nodes, {0, 2})

    def test_undirected_chain_spreads_from_both_ends(self) -> None:
        graph = nx.path_graph(5)
        result = run_cic(graph, [0], [4])
        self.assertEqual(result.rumor_nodes, {0, 1})
        self.assertEqual(result.protector_nodes, {2, 3, 4})
        self.assertEqual(result.steps, 2)
        self.assert_partition(graph, result)

    def test_isolated_seeds_do_not_spread(self) -> None:
        graph = nx.DiGraph([(0, 1)])
        graph.add_nodes_from([99, 100])
        result = run_cic(graph, [99], [100])
        self.assertEqual(result.rumor_nodes, {99})
        self.assertEqual(result.protector_nodes, {100})
        self.assertEqual(result.inactive_nodes, {0, 1})
        self.assertEqual(result.steps, 0)

    def test_overlapping_seeds_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "disjoint"):
            run_cic(nx.path_graph(3), [0, 1], [1, 2])

    def test_missing_seed_from_either_cascade_is_rejected(self) -> None:
        for rumor, protector in (([9000], [1]), ([0], [9000])):
            with self.subTest(rumor=rumor, protector=protector):
                with self.assertRaisesRegex(ValueError, "do not exist"):
                    run_cic(nx.path_graph(3), rumor, protector)

    def test_p_zero_activates_only_the_initial_seeds(self) -> None:
        graph = nx.path_graph(5)
        result = run_cic(graph, [0], [4], 0)
        self.assertEqual(result.rumor_nodes, {0})
        self.assertEqual(result.protector_nodes, {4})
        self.assertEqual(result.inactive_nodes, {1, 2, 3})
        self.assertEqual(result.steps, 0)
        self.assert_partition(graph, result)

    def test_p_one_matches_shortest_arrival_times_and_tie_rule(self) -> None:
        for directed in (False, True):
            graph = nx.gnp_random_graph(12, 0.16, seed=7, directed=directed)
            rumor_distance = nx.single_source_shortest_path_length(graph, 0)
            protector_distance = nx.single_source_shortest_path_length(graph, 11)
            for rule in TieBreakingRule:
                with self.subTest(directed=directed, rule=rule):
                    expected_rumor, expected_protector, expected_inactive = set(), set(), set()
                    for node in graph:
                        r = rumor_distance.get(node, float("inf"))
                        p = protector_distance.get(node, float("inf"))
                        if r == p == float("inf"):
                            expected_inactive.add(node)
                        elif r < p or (r == p and rule == TieBreakingRule.RUMOR_PRIORITY):
                            expected_rumor.add(node)
                        else:
                            expected_protector.add(node)
                    result = run_cic(graph, [0], [11], rule=rule)
                    self.assertEqual(result.rumor_nodes, expected_rumor)
                    self.assertEqual(result.protector_nodes, expected_protector)
                    self.assertEqual(result.inactive_nodes, expected_inactive)
                    self.assert_partition(graph, result)

    def test_cycles_self_loops_and_converging_paths_activate_each_node_once(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2), (2, 0), (2, 1), (2, 2), (2, 3), (3, 2)])
        result = run_cic(graph, [0], [1])
        self.assertEqual(result.rumor_nodes, {0})
        self.assertEqual(result.protector_nodes, {1, 2, 3})
        self.assert_partition(graph, result)

    def test_duplicate_seeds_are_combined_and_inputs_unchanged(self) -> None:
        rumor = [0, 0]
        protector = [3, 3]
        result = run_cic(nx.path_graph(4), rumor, protector, 0)
        self.assertEqual((result.rumor_count, result.protector_count), (1, 1))
        self.assertEqual(rumor, [0, 0])
        self.assertEqual(protector, [3, 3])

    def test_graph_topology_attributes_and_edge_weights_are_unchanged(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2)])
        graph.graph["label"] = "input"
        graph.nodes[2]["state"] = "inactive"
        graph.edges[1, 2]["weight"] = 0
        before = deepcopy(graph)
        result = run_cic(graph, [0], [1])
        self.assertTrue(nx.utils.graphs_equal(before, graph))
        self.assertIn(2, result.protector_nodes)

    def test_global_rng_state_is_unchanged(self) -> None:
        before = random.getstate()
        run_cic(nx.path_graph(5), [0], [4], 0.5)
        self.assertEqual(random.getstate(), before)

    def test_same_random_seed_reproduces_all_fields(self) -> None:
        graph = nx.gnp_random_graph(40, 0.2, seed=7, directed=True)
        first = run_cic(graph, [0, 3], [5, 9], 0.3)
        second = run_cic(graph, [0, 3], [5, 9], 0.3)
        self.assertEqual(first, second)
        self.assertGreater(first.rumor_count + first.protector_count, 4)
        self.assert_partition(graph, first)

    def test_random_seed_controls_the_sampled_outcome(self) -> None:
        graph = nx.DiGraph([(0, 2)])
        graph.add_node(1)
        self.assertIn(2, run_cic(graph, [0], [1], 0.5, seed=1).rumor_nodes)
        self.assertIn(2, run_cic(graph, [0], [1], 0.5, seed=2).inactive_nodes)

    def test_node_edge_and_seed_insertion_order_do_not_change_results(self) -> None:
        edges = [(0, 2), (0, 3), (1, 2), (1, 4), (2, 5), (3, 6), (4, 6), (5, 7), (6, 7)]
        first, second = nx.DiGraph(), nx.DiGraph()
        first.add_nodes_from(range(8))
        second.add_nodes_from(reversed(range(8)))
        first.add_edges_from(edges)
        second.add_edges_from(reversed(edges))
        for p in (0.2, 0.7, 1):
            for rule in TieBreakingRule:
                with self.subTest(p=p, rule=rule):
                    self.assertEqual(
                        run_cic(first, [0, 3], [1, 4], p, rule, seed=7),
                        run_cic(second, iter([3, 0, 3]), iter([4, 1, 1]), p, rule, seed=7),
                    )

    def test_hash_randomization_in_another_process_does_not_change_results(self) -> None:
        script = """
import json
import networkx as nx
from src.diffusion import simulate_cic
g = nx.DiGraph()
g.add_nodes_from({'r', 'p', 'r2', 'p2', 'a', 'b', 'c', 'd', 'e'})
g.add_edges_from({('r','a'), ('p','a'), ('r2','b'), ('p2','c'),
                  ('a','b'), ('b','d'), ('c','d'), ('d','e')})
r = simulate_cic(g, {'r','r2'}, {'p','p2'}, 0.6,
                 tie_breaking='protector-priority', random_seed=42)
print(json.dumps([sorted(r.rumor_nodes), sorted(r.protector_nodes),
                  sorted(r.inactive_nodes),
                  [[sorted(x.rumor_nodes), sorted(x.protector_nodes)]
                   for x in r.activation_layers]]))
"""
        outputs = []
        for hash_seed in ("1", "919"):
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=PROJECT_ROOT,
                env={**os.environ, "PYTHONHASHSEED": hash_seed},
                capture_output=True, text=True, check=True,
            )
            outputs.append(json.loads(completed.stdout))
        self.assertEqual(outputs[0], outputs[1])

    def test_mixed_supported_labels_have_a_stable_order(self) -> None:
        labels = ["r", "p", 9000, b"target", 2.5, ("tuple", 1), frozenset({"x", "y"}), False]
        edges = [("r", target) for target in labels[2:]] + [("p", b"target")]
        first, second = nx.DiGraph(), nx.DiGraph()
        first.add_nodes_from(labels)
        second.add_nodes_from(reversed(labels))
        first.add_edges_from(edges)
        second.add_edges_from(reversed(edges))
        for p in (0.5, 1):
            self.assertEqual(run_cic(first, ["r"], ["p"], p), run_cic(second, ["r"], ["p"], p))

    def test_unstable_or_nonfinite_node_labels_are_rejected(self) -> None:
        for label in (object(), float("nan"), float("inf")):
            with self.subTest(label=type(label)):
                graph = nx.path_graph(3)
                graph.add_node(label)
                with self.assertRaisesRegex(TypeError, "CIC node labels"):
                    run_cic(graph, [0], [2])

    def test_enum_tie_rule_matches_its_string_value(self) -> None:
        graph = nx.DiGraph([(0, 2), (1, 2)])
        self.assertEqual(
            run_cic(graph, [0], [1], rule=TieBreakingRule.PROTECTOR_PRIORITY),
            run_cic(graph, [0], [1], rule="protector-priority"),
        )

    def test_tie_rule_is_required_explicitly(self) -> None:
        with self.assertRaises(TypeError):
            simulate_cic(nx.path_graph(3), [0], [2], 0.5, random_seed=42)

    def test_unknown_tie_rule_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "tie_breaking"):
            run_cic(nx.path_graph(3), [0], [2], rule="first-visited")

    def test_invalid_tie_rule_type_is_rejected(self) -> None:
        for rule in (None, 1, True):
            with self.subTest(rule=rule):
                with self.assertRaisesRegex(TypeError, "tie_breaking"):
                    run_cic(nx.path_graph(3), [0], [2], rule=rule)

    def test_invalid_probability_values_are_rejected(self) -> None:
        for p in (-0.1, 1.1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(p=p):
                with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
                    run_cic(nx.path_graph(3), [0], [2], p)

    def test_invalid_probability_types_are_rejected(self) -> None:
        for p in (None, "0.5", True, complex(0.5, 0)):
            with self.subTest(p=p):
                with self.assertRaisesRegex(TypeError, "real number"):
                    run_cic(nx.path_graph(3), [0], [2], p)

    def test_invalid_random_seed_types_are_rejected(self) -> None:
        for seed in (True, 1.5, "42"):
            with self.subTest(seed=seed):
                with self.assertRaisesRegex(TypeError, "integer or None"):
                    run_cic(nx.path_graph(3), [0], [2], seed=seed)

    def test_unsupported_graph_types_are_rejected(self) -> None:
        for graph in (None, [(0, 1)], nx.MultiGraph([(0, 1)]), nx.MultiDiGraph([(0, 1)])):
            with self.subTest(graph=type(graph)):
                with self.assertRaisesRegex(TypeError, "simple NetworkX"):
                    run_cic(graph, [0], [1])

    def test_random_seed_is_optional(self) -> None:
        result = simulate_cic(nx.path_graph(3), [0], [2], 1, tie_breaking="protector-priority")
        self.assertEqual(result.rumor_nodes, {0})
        self.assertEqual(result.protector_nodes, {1, 2})


class ProcessedDatasetCICTests(CICAssertions):
    def test_p_zero_on_all_processed_datasets(self) -> None:
        for name in DATASETS:
            with self.subTest(dataset=name):
                graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
                rumor, protector = min(graph), max(graph)
                result = run_cic(graph, [rumor], [protector], 0)
                self.assertEqual(result.rumor_nodes, {rumor})
                self.assertEqual(result.protector_nodes, {protector})
                self.assertEqual(result.steps, 0)
                self.assert_partition(graph, result)

    def test_p_one_on_all_processed_datasets_matches_arrival_distances(self) -> None:
        for name in DATASETS:
            with self.subTest(dataset=name):
                graph = load_processed_graph(PROJECT_ROOT / "data/processed" / name)
                rumor, protector = min(graph), max(graph)
                r_distance = nx.single_source_shortest_path_length(graph, rumor)
                p_distance = nx.single_source_shortest_path_length(graph, protector)
                result = run_cic(nx.freeze(graph), [rumor], [protector])
                expected_rumor = {v for v in graph if r_distance.get(v, float("inf")) < p_distance.get(v, float("inf"))}
                expected_protector = {v for v in p_distance if p_distance[v] <= r_distance.get(v, float("inf"))}
                self.assertEqual(result.rumor_nodes, expected_rumor)
                self.assertEqual(result.protector_nodes, expected_protector)
                self.assert_partition(graph, result)

    def test_email_random_run_is_reproducible_after_reversing_graph_insertion(self) -> None:
        graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
        reversed_graph = nx.DiGraph()
        reversed_graph.add_nodes_from(reversed(list(graph)))
        reversed_graph.add_edges_from(reversed(list(graph.edges())))
        first = run_cic(graph, [0], [1], 0.05)
        self.assertEqual(first, run_cic(reversed_graph, [0], [1], 0.05))
        self.assert_partition(graph, first)

    def test_email_single_cascade_matches_existing_ic(self) -> None:
        graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
        ic = simulate_ic(graph, [0], 0.05, random_seed=42)
        cic = run_cic(graph, [0], [], 0.05)
        self.assertEqual(cic.rumor_nodes, ic.active_nodes)
        self.assertEqual(tuple(layer.rumor_nodes for layer in cic.activation_layers), ic.activation_layers)
        self.assertEqual(cic.steps, ic.steps)
