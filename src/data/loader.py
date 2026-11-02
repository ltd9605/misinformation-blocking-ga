"""Strict streaming readers for plain and gzip-compressed edge lists."""

from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import zlib

import networkx as nx

from .validation import DatasetValidationError


@dataclass(frozen=True)
class ReadStatistics:
    """Record counts collected before a simple graph can collapse edges."""

    edge_records: int
    duplicate_edges: int
    comment_lines: int
    blank_lines: int


@dataclass
class LoadedGraph:
    """A raw graph, its parse statistics and source fingerprint."""

    graph: nx.Graph
    statistics: ReadStatistics
    source_sha256: str


def sha256_file(path: Path) -> str:
    """Hash a file's bytes without decompressing or modifying it."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_edge_list(path: str | Path, *, directed: bool) -> LoadedGraph:
    """Read integer edge pairs; reject malformed lines and duplicate edges.

    Lines beginning with # are comments. Inline # comments are also accepted.
    Reverse pairs are duplicates only for undirected graphs. Archives such as
    .tar.gz are deliberately excluded from the edge-list interface.
    """
    path = Path(path)
    if path.name.lower().endswith((".tar.gz", ".tgz", ".tar")):
        raise DatasetValidationError(f"Archive is not an edge list: {path}")
    graph = nx.DiGraph() if directed else nx.Graph()
    records = duplicates = comments = blanks = 0
    first_duplicate = None
    try:
        source_hash = sha256_file(path)
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        with opener(path, "rt", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, start=1):
                stripped = line.strip()
                if not stripped:
                    blanks += 1
                    continue
                if stripped.startswith("#"):
                    comments += 1
                    continue
                parts = stripped.partition("#")[0].split()
                try:
                    if len(parts) != 2:
                        raise ValueError("expected two columns")
                    u, v = map(int, parts)
                except ValueError as exc:
                    raise DatasetValidationError(
                        f"{path}:{line_number}: expected two integer node IDs"
                    ) from exc
                records += 1
                if graph.has_edge(u, v):
                    duplicates += 1
                    if first_duplicate is None:
                        first_duplicate = line_number
                graph.add_edge(u, v)
        if sha256_file(path) != source_hash:
            raise DatasetValidationError(f"Source changed while reading: {path}")
    except (OSError, EOFError, UnicodeError, zlib.error) as exc:
        raise DatasetValidationError(f"Cannot read edge list {path}: {exc}") from exc
    if duplicates:
        raise DatasetValidationError(
            f"{path}:{first_duplicate}: {duplicates} duplicate edge record(s); "
            "no automatic deduplication is permitted"
        )
    if not records:
        raise DatasetValidationError(f"Edge list contains no edges: {path}")
    return LoadedGraph(graph, ReadStatistics(records, duplicates, comments, blanks), source_hash)
