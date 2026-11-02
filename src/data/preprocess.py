"""Conservative, explicitly configured topology preprocessing."""

import networkx as nx

from .specs import PreprocessConfig
from .validation import validate_graph, validate_preprocessing


def preprocess_graph(graph: nx.Graph, config: PreprocessConfig) -> nx.Graph:
    """Return a copy with configured self-loops removed and all nodes retained."""
    validate_graph(graph)
    processed = graph.copy()
    if config.remove_self_loops:
        processed.remove_edges_from(list(nx.selfloop_edges(processed)))
    validate_preprocessing(graph, processed, remove_self_loops=config.remove_self_loops)
    return processed
