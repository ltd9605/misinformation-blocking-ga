"""Synchronous Independent Cascade on simple NetworkX graphs."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from numbers import Real
from random import Random

import networkx as nx


@dataclass(frozen=True)
class ICResult:
    """Final active nodes and disjoint activation layers, with seeds at t=0.

    Layers contain only nonempty sets. Empty seeds produce no layers. The final
    unsuccessful round is not included in either the layers or the step count.
    """

    active_nodes: frozenset[Hashable]
    activation_layers: tuple[frozenset[Hashable], ...]

    @property
    def active_count(self) -> int:
        """Return the number of distinct active nodes, including seeds."""
        return len(self.active_nodes)

    @property
    def steps(self) -> int:
        """Return the number of successful propagation rounds after t=0."""
        return max(0, len(self.activation_layers) - 1)


def simulate_ic(
    graph: nx.Graph,
    seed_nodes: Iterable[Hashable],
    propagation_probability: float,
    *,
    random_seed: int | None = None,
) -> ICResult:
    """Simulate Independent Cascade without modifying the graph or seed input.

    Accept a simple Graph/DiGraph and one finite real probability in [0, 1],
    applied uniformly to every edge. Edge attributes are not used. All seeds
    must be graph nodes; duplicates are treated as one seed. Empty seeds are
    allowed. Missing seeds and invalid probability values raise ValueError;
    unsupported graph/probability/random-seed types raise TypeError.

    Each newly active source gets one independent attempt per inactive neighbor.
    Directed neighbors are successors. Successful targets enter the next round
    only; a target already scheduled for that round needs no further attempts.
    Cycles and self-loops cannot reactivate a node. Parallel edges are rejected.

    A local Random instance leaves Python's global RNG untouched. Traversal
    follows graph node insertion order, for both sources and neighbors, rather
    than set iteration or edge insertion order. The same graph node order,
    probability, seed set and integer random seed reproduce all result fields.
    Hashable node labels need not be mutually sortable. With random_seed=None,
    the local RNG is initialized from system entropy.
    """
    if not isinstance(graph, nx.Graph) or graph.is_multigraph():
        raise TypeError("graph must be a simple NetworkX Graph or DiGraph")
    if isinstance(propagation_probability, bool) or not isinstance(propagation_probability, Real):
        raise TypeError("propagation_probability must be a real number")
    if not 0 <= propagation_probability <= 1:
        raise ValueError("propagation_probability must be finite and in [0, 1]")
    if random_seed is not None and (isinstance(random_seed, bool) or not isinstance(random_seed, int)):
        raise TypeError("random_seed must be an integer or None")

    seeds = frozenset(seed_nodes)
    missing = seeds.difference(graph)
    if missing:
        raise ValueError(f"Seed nodes do not exist in graph: {missing!r}")
    if not seeds:
        return ICResult(frozenset(), ())

    rng = Random(random_seed)
    node_order = {node: position for position, node in enumerate(graph)}
    active = set(seeds)
    frontier = seeds
    layers = [seeds]
    while frontier:
        next_frontier: set[Hashable] = set()
        for source in sorted(frontier, key=node_order.__getitem__):
            for target in sorted(graph.neighbors(source), key=node_order.__getitem__):
                if target in active or target in next_frontier:
                    continue
                if rng.random() < propagation_probability:
                    next_frontier.add(target)
        if not next_frontier:
            break
        active.update(next_frontier)
        frontier = frozenset(next_frontier)
        layers.append(frontier)

    return ICResult(frozenset(active), tuple(layers))
