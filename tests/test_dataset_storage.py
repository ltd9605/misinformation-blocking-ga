from dataclasses import asdict
import json

import networkx as nx

from src.data.loader import sha256_file
from src.data.storage import load_processed_graph, save_processed_graph
from src.data.validation import DatasetValidationError, graph_statistics, validate_same_graph
from tests.helpers import TemporaryFilesTest, metadata_for


class StorageTests(TemporaryFilesTest):
    def test_round_trip_retains_sparse_ids_isolates_loops_and_direction(self):
        for graph_type in (nx.Graph, nx.DiGraph):
            with self.subTest(graph_type=graph_type):
                graph = graph_type([(90, 3), (7, 7)])
                graph.add_node(8000)
                directory = self.root / graph_type.__name__
                metadata = metadata_for(graph)
                saved = save_processed_graph(graph, metadata, directory)
                restored = load_processed_graph(directory)
                validate_same_graph(graph, restored)
                self.assertEqual(set(nx.isolates(restored)), {8000})
                self.assertNotIn("artifacts", metadata)
                self.assertEqual(saved["processed_statistics"], asdict(graph_statistics(restored)))

    def test_empty_graph_round_trip(self):
        graph = nx.DiGraph()
        save_processed_graph(graph, metadata_for(graph), self.root)
        validate_same_graph(graph, load_processed_graph(self.root))

    def test_output_is_deterministic_regardless_of_insertion_order(self):
        first = nx.Graph([(90, 3), (8, 7), (3, 7)])
        first.add_nodes_from([9000, 600])
        second = nx.Graph([(7, 3), (7, 8), (3, 90)])
        second.add_nodes_from([600, 9000])
        save_processed_graph(first, metadata_for(first), self.root / "a")
        save_processed_graph(second, metadata_for(second), self.root / "b")
        for name in ("nodes.csv", "edges.csv", "metadata.json"):
            self.assertEqual((self.root / "a" / name).read_bytes(), (self.root / "b" / name).read_bytes())

    def test_artifact_corruption_is_rejected(self):
        graph = nx.Graph([(3, 90)])
        for name in ("nodes.csv", "edges.csv"):
            with self.subTest(name=name):
                save_processed_graph(graph, metadata_for(graph), self.root)
                with (self.root / name).open("a", encoding="utf-8") as stream:
                    stream.write("9000\n")
                with self.assertRaisesRegex(DatasetValidationError, "checksum mismatch"):
                    load_processed_graph(self.root)

    def _replace_artifact(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")
        metadata_path = self.root / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["artifacts"][name]["sha256"] = sha256_file(self.root / name)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    def test_semantically_invalid_csv_is_rejected_even_with_matching_hash(self):
        graph = nx.Graph([(3, 90)])
        cases = (
            ("nodes.csv", "bad_header\n3\n90\n", "header"),
            ("nodes.csv", "node_id\n3\n90\n3\n", "duplicate node"),
            ("nodes.csv", "node_id\n3,90\n", "one column"),
            ("nodes.csv", "node_id\n3\n90\n1000\n", "statistics"),
            ("edges.csv", "source,target\n3,999\n", "unknown node"),
            ("edges.csv", "source,target\n3,90\n90,3\n", "duplicate edge"),
            ("edges.csv", "source,target\n3\n", "two columns"),
            ("edges.csv", "source,target\nx,90\n", "Cannot load"),
        )
        for name, contents, message in cases:
            with self.subTest(contents=contents):
                save_processed_graph(graph, metadata_for(graph), self.root)
                self._replace_artifact(name, contents)
                with self.assertRaisesRegex(DatasetValidationError, message):
                    load_processed_graph(self.root)

    def test_invalid_metadata_and_missing_files_are_rejected(self):
        graph = nx.Graph([(3, 90)])
        cases = ([], {"schema_version": 2}, {"schema_version": 1, "directed": "false"})
        for contents in cases:
            with self.subTest(contents=contents):
                save_processed_graph(graph, metadata_for(graph), self.root)
                (self.root / "metadata.json").write_text(json.dumps(contents), encoding="utf-8")
                with self.assertRaises(DatasetValidationError):
                    load_processed_graph(self.root)
        with self.assertRaisesRegex(DatasetValidationError, "Cannot load"):
            load_processed_graph(self.root / "missing")

    def test_bad_export_metadata_is_rejected_before_writing(self):
        graph = nx.Graph([(3, 90)])
        for update in ({"directed": True}, {"processed_statistics": {}}, {"schema_version": 2}):
            with self.subTest(update=update):
                with self.assertRaises(DatasetValidationError):
                    save_processed_graph(graph, {**metadata_for(graph), **update}, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_raw_output_directories_are_protected(self):
        graph = nx.Graph([(3, 90)])
        raw = self.root / "raw"
        raw.mkdir()
        source = raw / "nodes.csv"
        source.write_text("original raw bytes", encoding="utf-8")
        for output in (raw, raw / "nested"):
            with self.subTest(output=output):
                with self.assertRaisesRegex(DatasetValidationError, "protected raw"):
                    save_processed_graph(graph, metadata_for(graph), output, protected_paths=(raw,))
        self.assertEqual(source.read_text(encoding="utf-8"), "original raw bytes")

    def test_default_raw_directory_is_protected(self):
        from src.data.specs import PROJECT_ROOT

        graph = nx.Graph([(3, 90)])
        with self.assertRaisesRegex(DatasetValidationError, "protected raw"):
            save_processed_graph(graph, metadata_for(graph), PROJECT_ROOT / "data/raw/email-Eu-core")
