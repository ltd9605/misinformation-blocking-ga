import unittest

import networkx as nx

from src.data import PreprocessConfig, preprocess_graph
from src.data.validation import validate_same_graph


class PreprocessTests(unittest.TestCase):
    def test_loop_only_nodes_survive_without_mutating_input(self):
        for graph_type in (nx.Graph, nx.DiGraph):
            with self.subTest(graph_type=graph_type):
                graph = graph_type([(3, 3), (90, 7), (90, 90)])
                graph.add_node(800)
                original = graph.copy()
                processed = preprocess_graph(graph, PreprocessConfig(True))
                self.assertEqual(set(processed), {3, 90, 7, 800})
                self.assertEqual(processed.number_of_edges(), 1)
                self.assertFalse(list(nx.selfloop_edges(processed)))
                self.assertEqual(set(nx.isolates(processed)), {3, 800})
                validate_same_graph(graph, original)

    def test_keep_loops_returns_independent_unchanged_copy(self):
        graph = nx.DiGraph([(3, 3), (3, 90)])
        processed = preprocess_graph(graph, PreprocessConfig(False))
        self.assertIsNot(processed, graph)
        validate_same_graph(graph, processed)

    def test_preprocessing_is_idempotent(self):
        graph = nx.DiGraph([(3, 3), (3, 90)])
        once = preprocess_graph(graph, PreprocessConfig(True))
        twice = preprocess_graph(once, PreprocessConfig(True))
        validate_same_graph(once, twice)

    def test_empty_graph_is_preserved(self):
        for directed in (True, False):
            graph = nx.DiGraph() if directed else nx.Graph()
            validate_same_graph(graph, preprocess_graph(graph, PreprocessConfig(True)))
