"""Synchronous Competitive Independent Cascade with explicit tie rules."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from numbers import Real
from random import Random
from typing import Any

import networkx as nx


class TieBreakingRule(StrEnum):
    """Resolve successful proposals from both cascades in the same timestep."""

    PROTECTOR_PRIORITY = "protector-priority"
    RUMOR_PRIORITY = "rumor-priority"


@dataclass(frozen=True)
class CICLayer:
    """Nodes newly activated at one timestep, separated by their final state."""

    rumor_nodes: frozenset[Hashable]
    protector_nodes: frozenset[Hashable]


@dataclass(frozen=True)
class CICResult:
    """Immutable final partition and activation layers, including seeds at t=0.

    A node belongs to exactly one final set. No node occurs in more than one
    activation layer. Both seed sets empty means no layers and zero steps.
    """

    rumor_nodes: frozenset[Hashable]
    protector_nodes: frozenset[Hashable]
    inactive_nodes: frozenset[Hashable]
    activation_layers: tuple[CICLayer, ...]

    @property
    def rumor_count(self) -> int:
        """Return the number of rumor nodes, including rumor seeds."""
        return len(self.rumor_nodes)

    @property
    def protector_count(self) -> int:
        """Return the number of protector nodes, including protector seeds."""
        return len(self.protector_nodes)

    @property
    def inactive_count(self) -> int:
        """Return the number of nodes never activated by either cascade."""
        return len(self.inactive_nodes)

    @property
    def steps(self) -> int:
        """Count successful propagation rounds after t=0, as in ICResult."""
        return max(0, len(self.activation_layers) - 1)


def _node_sort_key(node: Hashable) -> tuple[str, Any]:
    """Give supported built-in labels a stable, insertion-independent order.

    Custom objects, repr-based ordering and Python hashes cannot in general
    provide this guarantee. Reject them instead of silently breaking replay.
    """
    if type(node) in (bool, int, str, bytes):
        return (type(node).__name__, node)
    if type(node) is float and isfinite(node):
        return ("float", node)
    if type(node) is tuple:
        return ("tuple", tuple(_node_sort_key(item) for item in node))
    if type(node) is frozenset:
        return ("frozenset", tuple(sorted(_node_sort_key(item) for item in node)))
    raise TypeError(
        "CIC node labels must be built-in int/bool/str/bytes, finite float, "
        "or tuples/frozensets of these types"
    )


def simulate_cic(
    graph: nx.Graph,
    rumor_seeds: Iterable[Hashable],
    protector_seeds: Iterable[Hashable],
    propagation_probability: float,
    *,
    tie_breaking: TieBreakingRule | str,
    random_seed: int | None = None,
) -> CICResult:
    """Simulate competing RUMOR/PROTECTOR cascades without modifying inputs.

    Accept a simple Graph/DiGraph, disjoint seed sets and a shared finite real
    p in [0, 1]. All seeds must exist; duplicates within a cascade are combined.
    Parallel edges are rejected; edge attributes are ignored, matching IC.
    The tie rule is required explicitly, as an enum or its string value.

    At each timestep, only the previous layer can transmit. Each newly active
    source gets one Bernoulli attempt per inactive neighbor (successor for a
    DiGraph). Successful proposals are collected independently for the two
    cascades. A same-cascade success can skip further proposals to that target;
    it never suppresses the competing cascade's attempt in the same timestep.
    Only after all sources have tried are ties resolved and new states fixed.
    Existing active nodes cannot change state or be reactivated.

    Source and neighbor traversal uses canonical label order, independent of
    graph/seed insertion order and hash randomization. Supported labels are
    documented in _node_sort_key. Random uses a private RNG; an integer seed
    reproduces the complete result. None uses system initialization.

    Invalid graph, probability type, random-seed type, tie-rule type or node
    label raises TypeError. Overlapping/missing seeds, out-of-range probability
    (including NaN/infinity), and unknown tie-rule strings raise ValueError.
    """
    if not isinstance(graph, nx.Graph) or graph.is_multigraph():
        raise TypeError("graph must be a simple NetworkX Graph or DiGraph")
    if isinstance(propagation_probability, bool) or not isinstance(propagation_probability, Real):
        raise TypeError("propagation_probability must be a real number")
    if not 0 <= propagation_probability <= 1:
        raise ValueError("propagation_probability must be finite and in [0, 1]")
    if random_seed is not None and (isinstance(random_seed, bool) or not isinstance(random_seed, int)):
        raise TypeError("random_seed must be an integer or None")
    if not isinstance(tie_breaking, str):
        raise TypeError("tie_breaking must be a TieBreakingRule or string")
    try:
        rule = TieBreakingRule(tie_breaking)
    except ValueError as exc:
        raise ValueError("tie_breaking must be 'protector-priority' or 'rumor-priority'") from exc

    rumor = set(rumor_seeds)
    protector = set(protector_seeds)
    if rumor & protector:
        raise ValueError("Rumor and protector seeds must be disjoint")
    active = rumor | protector
    missing = active.difference(graph)
    if missing:
        raise ValueError(f"Seed nodes do not exist in graph: {missing!r}")
    nodes = frozenset(graph)
    ordered_nodes = sorted(graph, key=_node_sort_key)
    node_order = {node: position for position, node in enumerate(ordered_nodes)}
    layers = [CICLayer(frozenset(rumor), frozenset(protector))] if active else []
    rumor_frontier = set(rumor)
    protector_frontier = set(protector)
    rng = Random(random_seed)

    while rumor_frontier or protector_frontier:
        rumor_proposals: set[Hashable] = set()
        protector_proposals: set[Hashable] = set()
        for source in sorted(rumor_frontier | protector_frontier, key=node_order.__getitem__):
            proposals = rumor_proposals if source in rumor_frontier else protector_proposals
            for target in sorted(graph.neighbors(source), key=node_order.__getitem__):
                if target in active or target in proposals:
                    continue
                if rng.random() < propagation_probability:
                    proposals.add(target)

        # Resolve only after collecting both cascades' independent successes.
        if rule == TieBreakingRule.PROTECTOR_PRIORITY:
            rumor_proposals.difference_update(protector_proposals)
        else:
            protector_proposals.difference_update(rumor_proposals)
        new_active = rumor_proposals | protector_proposals
        if not new_active:
            break
        rumor.update(rumor_proposals)
        protector.update(protector_proposals)
        active.update(new_active)
        rumor_frontier = rumor_proposals
        protector_frontier = protector_proposals
        layers.append(CICLayer(frozenset(rumor_frontier), frozenset(protector_frontier)))

    return CICResult(
        frozenset(rumor), frozenset(protector), nodes.difference(active), tuple(layers),
    )
