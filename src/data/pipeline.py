"""Orchestrate the Milestone 1 dataset pipeline."""

from dataclasses import asdict, dataclass
from pathlib import Path
import platform
from typing import Any

import networkx as nx

from .loader import load_edge_list, sha256_file
from .preprocess import preprocess_graph
from .specs import PROJECT_ROOT, PreprocessConfig, get_dataset_spec
from .storage import load_processed_graph, save_processed_graph
from .validation import (
    DatasetValidationError, graph_statistics, validate_counts, validate_same_graph,
)


@dataclass
class PipelineResult:
    """Verified graph and the provenance written alongside it."""

    graph: nx.Graph
    metadata: dict[str, Any]
    output_directory: Path


def prepare_dataset(
    name: str,
    *,
    raw_directory: str | Path | None = None,
    output_directory: str | Path | None = None,
    config: PreprocessConfig | None = None,
) -> PipelineResult:
    """Validate raw data, preprocess, persist and verify an exact round-trip."""
    spec = get_dataset_spec(name)
    raw_directory = Path(raw_directory) if raw_directory is not None else PROJECT_ROOT / "data/raw"
    output_directory = (
        Path(output_directory) if output_directory is not None
        else PROJECT_ROOT / "data/processed" / name
    )
    config = config if config is not None else PreprocessConfig(spec.remove_self_loops)
    source = raw_directory / spec.relative_path
    loaded = load_edge_list(source, directed=spec.directed)
    validate_counts(loaded.graph, spec.expected_nodes, spec.expected_edges)
    before = graph_statistics(loaded.graph)
    processed = preprocess_graph(loaded.graph, config)
    after = graph_statistics(processed)
    resolved_raw_directory = raw_directory.resolve()
    try:
        source_directory = resolved_raw_directory.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        source_directory = str(resolved_raw_directory)
    metadata = {
        "schema_version": 1,
        "dataset": name,
        "directed": spec.directed,
        "node_id_type": "integer",
        "source": {
            "raw_directory": source_directory,
            "path": spec.relative_path.as_posix(),
            "sha256": loaded.source_sha256,
        },
        "expected_raw_counts": {"node_count": spec.expected_nodes, "edge_count": spec.expected_edges},
        "raw_statistics": {**asdict(before), **asdict(loaded.statistics)},
        "preprocessing": asdict(config),
        "transformations": [{
            "operation": "remove_self_loops",
            "enabled": config.remove_self_loops,
            "removed_edges": before.edge_count - after.edge_count,
            "removed_nodes": 0,
        }],
        "processed_statistics": asdict(after),
        "environment": {"python": platform.python_version(), "networkx": nx.__version__},
    }
    metadata = save_processed_graph(
        processed, metadata, output_directory, protected_paths=(raw_directory, source),
    )
    restored = load_processed_graph(output_directory)
    validate_same_graph(processed, restored)
    if sha256_file(source) != loaded.source_sha256:
        raise DatasetValidationError(f"Raw source changed during pipeline: {source}")
    return PipelineResult(restored, metadata, output_directory.resolve())
