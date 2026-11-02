"""Temporary files shared by dataset tests."""

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import networkx as nx

from src.data.validation import graph_statistics


class TemporaryFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, text: str, name: str = "edges.txt") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def metadata_for(graph: nx.Graph) -> dict:
    return {
        "schema_version": 1,
        "dataset": "unit-test-fixture",
        "directed": graph.is_directed(),
        "processed_statistics": asdict(graph_statistics(graph)),
    }
