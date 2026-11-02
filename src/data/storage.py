"""Deterministic CSV/JSON artifacts preserving isolated nodes and provenance."""

import copy
import csv
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import networkx as nx

from .loader import sha256_file
from .specs import PROJECT_ROOT
from .validation import DatasetValidationError, edge_set, graph_statistics, validate_graph


def _check_output_paths(directory: Path, protected_paths: tuple[Path, ...]) -> None:
    """Prevent writes into raw data, including through existing symlinks."""
    protected = (PROJECT_ROOT / "data/raw", *protected_paths)
    targets = (directory, *(directory / name for name in ("nodes.csv", "edges.csv", "metadata.json")))
    for target in targets:
        resolved = target.resolve()
        for source in protected:
            source = source.resolve()
            if resolved == source or resolved.is_relative_to(source):
                raise DatasetValidationError(f"Output would overwrite protected raw data: {target}")


def _check_metadata(metadata: dict[str, Any]) -> None:
    if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
        raise DatasetValidationError("Unsupported metadata schema_version")
    if type(metadata.get("directed")) is not bool:
        raise DatasetValidationError("Metadata directed must be a boolean")
    if not isinstance(metadata.get("processed_statistics"), dict):
        raise DatasetValidationError("Metadata is missing processed_statistics")


def save_processed_graph(
    graph: nx.Graph,
    metadata: dict[str, Any],
    directory: str | Path,
    *,
    protected_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Write sorted node/edge CSVs and metadata with artifact checksums.

    The separate node table retains isolated nodes. Existing artifacts may be
    regenerated; staging prevents serialization errors from replacing them.
    """
    directory = Path(directory)
    _check_output_paths(directory, protected_paths)
    validate_graph(graph)
    _check_metadata(metadata)
    if metadata["directed"] != graph.is_directed():
        raise DatasetValidationError("Metadata directedness differs from graph")
    if metadata["processed_statistics"] != asdict(graph_statistics(graph)):
        raise DatasetValidationError("Metadata statistics differ from graph")
    saved_metadata = copy.deepcopy(metadata)
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".dataset-", dir=directory) as staging:
        staging = Path(staging)
        with (staging / "nodes.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["node_id"])
            writer.writerows((node,) for node in sorted(graph))
        with (staging / "edges.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["source", "target"])
            writer.writerows(sorted(edge_set(graph)))
        saved_metadata["artifacts"] = {
            name: {"sha256": sha256_file(staging / name)}
            for name in ("nodes.csv", "edges.csv")
        }
        (staging / "metadata.json").write_text(
            json.dumps(saved_metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        for name in ("nodes.csv", "edges.csv", "metadata.json"):
            (staging / name).replace(directory / name)
    return saved_metadata


def load_processed_graph(directory: str | Path) -> nx.Graph:
    """Read a processed graph, checking checksums, references and counts."""
    directory = Path(directory)
    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise DatasetValidationError("Metadata must be a JSON object")
        _check_metadata(metadata)
        for name in ("nodes.csv", "edges.csv"):
            if sha256_file(directory / name) != metadata["artifacts"][name]["sha256"]:
                raise DatasetValidationError(f"Artifact checksum mismatch: {name}")
        graph = nx.DiGraph() if metadata["directed"] else nx.Graph()
        with (directory / "nodes.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            if next(reader, None) != ["node_id"]:
                raise DatasetValidationError("Invalid nodes.csv header")
            for line_number, row in enumerate(reader, start=2):
                if len(row) != 1:
                    raise DatasetValidationError(f"nodes.csv:{line_number}: expected one column")
                node = int(row[0])
                if node in graph:
                    raise DatasetValidationError(f"nodes.csv:{line_number}: duplicate node ID")
                graph.add_node(node)
        with (directory / "edges.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            if next(reader, None) != ["source", "target"]:
                raise DatasetValidationError("Invalid edges.csv header")
            for line_number, row in enumerate(reader, start=2):
                if len(row) != 2:
                    raise DatasetValidationError(f"edges.csv:{line_number}: expected two columns")
                u, v = map(int, row)
                if u not in graph or v not in graph:
                    raise DatasetValidationError(f"edges.csv:{line_number}: unknown node ID")
                if graph.has_edge(u, v):
                    raise DatasetValidationError(f"edges.csv:{line_number}: duplicate edge")
                graph.add_edge(u, v)
        if asdict(graph_statistics(graph)) != metadata["processed_statistics"]:
            raise DatasetValidationError("Processed graph statistics do not match metadata")
        return graph
    except DatasetValidationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        raise DatasetValidationError(f"Cannot load processed dataset {directory}: {exc}") from exc
