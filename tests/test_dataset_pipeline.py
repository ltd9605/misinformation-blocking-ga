from dataclasses import replace
import gzip
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import networkx as nx

from src.data import DatasetValidationError, PreprocessConfig, prepare_dataset
from src.data.loader import sha256_file
from src.data.specs import DATASETS, PROJECT_ROOT, DatasetSpec
from src.data.validation import validate_same_graph
from tests.helpers import TemporaryFilesTest


class PipelineTests(TemporaryFilesTest):
    def setUp(self):
        super().setUp()
        self.raw = self.root / "raw"
        self.raw.mkdir()
        with gzip.open(self.raw / "fixture.txt.gz", "wt", encoding="utf-8") as stream:
            stream.write("# fixture\n3 3\n90 7\n")
        self.spec = DatasetSpec("fixture", Path("fixture.txt.gz"), True, 3, 2, True)
        registry = patch.dict(DATASETS, {"fixture": self.spec})
        registry.start()
        self.addCleanup(registry.stop)

    def run_pipeline(self, **kwargs):
        return prepare_dataset(
            "fixture", raw_directory=self.raw, output_directory=self.root / "out", **kwargs,
        )

    def test_pipeline_records_provenance_and_is_repeatable(self):
        before_hash = sha256_file(self.raw / "fixture.txt.gz")
        first = self.run_pipeline()
        artifact_bytes = {path.name: path.read_bytes() for path in first.output_directory.iterdir()}
        second = self.run_pipeline()
        validate_same_graph(first.graph, second.graph)
        self.assertEqual(first.metadata, second.metadata)
        self.assertEqual(artifact_bytes, {path.name: path.read_bytes() for path in second.output_directory.iterdir()})
        self.assertEqual(first.metadata["source"]["sha256"], before_hash)
        self.assertEqual(sha256_file(self.raw / "fixture.txt.gz"), before_hash)
        self.assertEqual(first.metadata["raw_statistics"]["edge_records"], 2)
        self.assertEqual(first.metadata["transformations"][0]["removed_edges"], 1)
        self.assertEqual(set(nx.isolates(first.graph)), {3})

    def test_explicit_preprocessing_override_is_recorded(self):
        result = self.run_pipeline(config=PreprocessConfig(False))
        self.assertEqual(result.graph.number_of_edges(), 2)
        self.assertEqual(result.metadata["preprocessing"], {"remove_self_loops": False})
        self.assertEqual(result.metadata["transformations"][0]["removed_edges"], 0)

    def test_bad_raw_counts_prevent_export(self):
        DATASETS["fixture"] = replace(self.spec, expected_nodes=4)
        with self.assertRaisesRegex(DatasetValidationError, "Count mismatch"):
            self.run_pipeline()
        self.assertFalse((self.root / "out").exists())

    def test_pipeline_cannot_export_into_its_raw_directory(self):
        before = sha256_file(self.raw / "fixture.txt.gz")
        with self.assertRaisesRegex(DatasetValidationError, "protected raw"):
            prepare_dataset("fixture", raw_directory=self.raw, output_directory=self.raw)
        self.assertEqual(sha256_file(self.raw / "fixture.txt.gz"), before)
        self.assertEqual(len(list(self.raw.iterdir())), 1)


class RealDatasetTests(TemporaryFilesTest):
    def test_all_three_datasets_counts_round_trip_and_all_raw_hashes(self):
        raw = PROJECT_ROOT / "data/raw"
        before = {path: sha256_file(path) for path in raw.rglob("*") if path.is_file()}
        expectations = {
            "email-Eu-core": (1005, 25571, 24929, 642, 19, True),
            "ego-Facebook": (4039, 88234, 88234, 0, 0, False),
            "Wiki-Vote": (7115, 103689, 103689, 0, 0, True),
        }
        for name, (nodes, raw_edges, processed_edges, loops, isolates, directed) in expectations.items():
            with self.subTest(dataset=name):
                result = prepare_dataset(name, output_directory=self.root / name)
                self.assertEqual(result.graph.number_of_nodes(), nodes)
                self.assertEqual(result.graph.number_of_edges(), processed_edges)
                self.assertEqual(result.graph.is_directed(), directed)
                self.assertEqual(nx.number_of_selfloops(result.graph), 0)
                self.assertEqual(len(list(nx.isolates(result.graph))), isolates)
                self.assertEqual(result.metadata["raw_statistics"]["edge_count"], raw_edges)
                self.assertEqual(result.metadata["raw_statistics"]["self_loop_count"], loops)
                self.assertEqual(result.metadata["raw_statistics"]["duplicate_edges"], 0)
                if name == "Wiki-Vote":
                    self.assertEqual((min(result.graph), max(result.graph)), (3, 8297))
                    self.assertNotIn(0, result.graph)
        after = {path: sha256_file(path) for path in raw.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_real_email_loop_policy_can_be_overridden(self):
        result = prepare_dataset(
            "email-Eu-core", output_directory=self.root / "email-keep",
            config=PreprocessConfig(False),
        )
        self.assertEqual(result.graph.number_of_nodes(), 1005)
        self.assertEqual(result.graph.number_of_edges(), 25571)
        self.assertEqual(nx.number_of_selfloops(result.graph), 642)

    def test_cli_runs_each_dataset_from_another_working_directory(self):
        for name in ("email-Eu-core", "ego-Facebook", "Wiki-Vote"):
            with self.subTest(dataset=name):
                completed = subprocess.run(
                    [sys.executable, "-B", str(PROJECT_ROOT / "main.py"), "dataset",
                     "--name", name, "--output-dir", str(self.root / name)],
                    cwd=self.root, capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn(f"Dataset: {name}", completed.stdout)
                self.assertIn("exact topology round-trip", completed.stdout)
                self.assertTrue((self.root / name / "metadata.json").is_file())

    def test_cli_reports_missing_source_without_traceback(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(PROJECT_ROOT / "main.py"), "dataset", "--name",
             "Wiki-Vote", "--raw-dir", str(self.root / "absent")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Dataset pipeline failed", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
