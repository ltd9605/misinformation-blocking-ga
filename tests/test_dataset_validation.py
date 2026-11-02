import unittest

import networkx as nx

from src.data.specs import get_dataset_spec
from src.data.validation import (
    DatasetValidationError, graph_statistics, validate_counts,
    validate_graph, validate_preprocessing,
)


class ValidationTests(unittest.TestCase):
    def test_statistics_include_isolated_nodes(self):
        graph = nx.DiGraph([(3, 90), (90, 3), (7, 7)])
        graph.add_node(500)
        stats = graph_statistics(graph)
        self.assertEqual((stats.node_count, stats.edge_count), (4, 3))
        self.assertEqual(stats.self_loop_count, 1)
        self.assertEqual(stats.isolated_node_count, 1)

    def test_expected_counts_validate_nodes_and_edges(self):
        graph = nx.Graph([(3, 99)])
        validate_counts(graph, 2, 1)
        for nodes, edges in ((3, 1), (2, 2)):
            with self.subTest(nodes=nodes, edges=edges):
                with self.assertRaisesRegex(DatasetValidationError, "Count mismatch"):
                    validate_counts(graph, nodes, edges)

    def test_noninteger_nodes_and_multigraphs_are_rejected(self):
        for graph in (nx.Graph([("3", "4")]), nx.Graph([(True, 3)]), nx.MultiDiGraph()):
            with self.subTest(graph=type(graph)):
                with self.assertRaises(DatasetValidationError):
                    validate_graph(graph)

    def test_unapproved_node_edge_and_direction_changes_are_rejected(self):
        original = nx.DiGraph([(3, 90), (90, 7)])
        missing_node = original.copy()
        missing_node.remove_node(7)
        missing_edge = original.copy()
        missing_edge.remove_edge(3, 90)
        added_edge = original.copy()
        added_edge.add_edge(7, 3)
        for altered in (missing_node, missing_edge, added_edge, original.to_undirected()):
            with self.subTest(edges=list(altered.edges)):
                with self.assertRaises(DatasetValidationError):
                    validate_preprocessing(original, altered, remove_self_loops=True)

    def test_registry_selects_topology_files_and_graph_types(self):
        self.assertTrue(get_dataset_spec("email-Eu-core").directed)
        self.assertFalse(get_dataset_spec("ego-Facebook").directed)
        self.assertEqual(get_dataset_spec("ego-Facebook").relative_path.name, "facebook_combined.txt.gz")
        self.assertEqual(get_dataset_spec("Wiki-Vote").relative_path.parent.name, "wiki-Vote")
        with self.assertRaisesRegex(ValueError, "Unknown dataset"):
            get_dataset_spec("unknown")
