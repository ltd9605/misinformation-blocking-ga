"""Reproducible, topology-preserving protector selection baselines."""

from collections.abc import Hashable, Iterable
from math import isfinite
from numbers import Real
from random import Random

import networkx as nx

from src.diffusion.cic import _node_sort_key


def _candidates(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
) -> tuple[list[Hashable], list[Hashable]]:
    """Validate the budget and reuse CIC's canonical supported-label ordering."""
    if not isinstance(graph, nx.Graph) or graph.is_multigraph():
        raise TypeError("graph must be a simple NetworkX Graph or DiGraph")
    if isinstance(k, bool) or not isinstance(k, int):
        raise TypeError("k must be an integer")
    if k < 0:
        raise ValueError("k must be nonnegative")
    rumor = frozenset(rumor_seeds)
    if rumor.difference(graph):
        raise ValueError("Rumor seeds must exist in graph")
    nodes = sorted(graph, key=_node_sort_key)
    candidates = [node for node in nodes if node not in rumor]
    if k > len(candidates):
        raise ValueError("k exceeds the number of eligible non-rumor nodes")
    return nodes, candidates


def select_random(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
    *, random_seed: int | None = None,
) -> frozenset[Hashable]:
    """Uniformly sample k distinct eligible nodes using a private RNG.

    Sampling from canonical label order makes a fixed integer seed independent
    of graph insertion order. Empty budgets return an empty set. None does not
    guarantee replay. Supported labels and graph types are the same as CIC.
    """
    _, candidates = _candidates(graph, rumor_seeds, k)
    if random_seed is not None and (isinstance(random_seed, bool) or not isinstance(random_seed, int)):
        raise TypeError("random_seed must be an integer or None")
    return frozenset(Random(random_seed).sample(candidates, k))


def select_degree(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
) -> frozenset[Hashable]:
    """Select by descending unweighted out-degree (directed) or degree.

    Equal scores use ascending canonical node label order. Dividing all scores
    by n-1 would give the same ranking, so raw degree counts are used. Self-loop
    counting follows NetworkX: one for out-degree, two for undirected degree.
    Rumor nodes remain in the graph and participate in degree calculation.
    """
    _, candidates = _candidates(graph, rumor_seeds, k)
    degree = graph.out_degree if graph.is_directed() else graph.degree
    # Python's stable sort preserves canonical label order on equal scores.
    ranked = sorted(candidates, key=lambda node: -degree(node))
    return frozenset(ranked[:k])


def select_pagerank(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
    *, alpha: float = 0.85, tol: float = 1e-12, max_iter: int = 1000,
) -> frozenset[Hashable]:
    """Select descending PageRank scores on the entire unweighted graph.

    Use NetworkX PageRank (SciPy backend), uniform teleportation/dangling mass,
    weight=None, and filter rumor nodes only after computing scores. Undirected
    edges are treated in both directions by NetworkX. Equal numerical scores
    use ascending canonical labels. A canonical graph copy fixes matrix and
    summation order while preserving the input graph, isolated nodes and loops.
    Convergence errors propagate; no fallback silently changes the algorithm.
    """
    nodes, candidates = _candidates(graph, rumor_seeds, k)
    for name, value in (("alpha", alpha), ("tol", tol)):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a finite real number")
        if not isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0 <= alpha < 1:
        raise ValueError("alpha must be in [0, 1)")
    if tol <= 0:
        raise ValueError("tol must be positive")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int):
        raise TypeError("max_iter must be a positive integer")
    if max_iter < 1:
        raise ValueError("max_iter must be positive")
    if k == 0:
        return frozenset()
    rank = {node: index for index, node in enumerate(nodes)}
    edges = list(graph.edges())
    if not graph.is_directed():
        edges = [(u, v) if rank[u] <= rank[v] else (v, u) for u, v in edges]
    edges.sort(key=lambda pair: (rank[pair[0]], rank[pair[1]]))
    canonical = nx.DiGraph() if graph.is_directed() else nx.Graph()
    canonical.add_nodes_from(nodes)
    canonical.add_edges_from(edges)
    scores = nx.pagerank(canonical, alpha=alpha, tol=tol, max_iter=max_iter, weight=None)
    ranked = sorted(candidates, key=lambda node: -scores[node])
    return frozenset(ranked[:k])
