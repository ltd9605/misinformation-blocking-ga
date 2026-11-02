"""Dataset statistics and topology invariants."""

from dataclasses import dataclass

import networkx as nx


class DatasetValidationError(ValueError):
    """Indicate invalid input data or an unexpected topology change."""


@dataclass(frozen=True)
class GraphStatistics:
    """Counts for a simple graph, including isolated vertices."""

    node_count: int
    edge_count: int
    self_loop_count: int
    isolated_node_count: int


def validate_graph(graph: nx.Graph) -> None:
    """Require a simple graph whose node IDs are Python integers."""
    if graph.is_multigraph():
        raise DatasetValidationError("MultiGraph/MultiDiGraph is not supported")
    if any(type(node) is not int for node in graph):
        raise DatasetValidationError("All node IDs must be integers")


def graph_statistics(graph: nx.Graph) -> GraphStatistics:
    """Compute counts without changing graph structure."""
    validate_graph(graph)
    return GraphStatistics(
        graph.number_of_nodes(), graph.number_of_edges(),
        nx.number_of_selfloops(graph), sum(1 for _ in nx.isolates(graph)),
    )


def edge_set(graph: nx.Graph) -> set[tuple[int, int]]:
    """Return comparable edges, canonicalizing undirected endpoints."""
    if graph.is_directed():
        return set(graph.edges())
    return {(min(u, v), max(u, v)) for u, v in graph.edges()}


def validate_counts(graph: nx.Graph, expected_nodes: int, expected_edges: int) -> None:
    """Reject raw counts that differ from the dataset specification."""
    actual = graph_statistics(graph)
    if actual.node_count != expected_nodes or actual.edge_count != expected_edges:
        raise DatasetValidationError(
            f"Count mismatch: expected {expected_nodes} nodes/{expected_edges} edges; "
            f"got {actual.node_count} nodes/{actual.edge_count} edges"
        )


def validate_preprocessing(
    before: nx.Graph, after: nx.Graph, *, remove_self_loops: bool,
) -> None:
    """Ensure preprocessing preserves every node and all permitted edges."""
    validate_graph(before)
    validate_graph(after)
    if before.is_directed() != after.is_directed():
        raise DatasetValidationError("Preprocessing changed directedness")
    if set(before) != set(after):
        raise DatasetValidationError("Preprocessing changed the node set")
    expected = edge_set(before)
    if remove_self_loops:
        expected = {(u, v) for u, v in expected if u != v}
    if edge_set(after) != expected:
        raise DatasetValidationError("Preprocessing changed edges outside its policy")


def validate_same_graph(expected: nx.Graph, actual: nx.Graph) -> None:
    """Require an exact topology match after serialization."""
    validate_preprocessing(expected, actual, remove_self_loops=False)
