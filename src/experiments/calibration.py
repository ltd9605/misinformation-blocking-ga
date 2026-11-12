"""Topology and sampling diagnostics for Pilot 2; verified simulators unchanged."""

from collections import Counter
from itertools import combinations
import hashlib
from math import sqrt
from random import Random
from statistics import mean, pstdev, stdev
from typing import Any

import networkx as nx
from scipy.stats import t


def reachable_sizes(graph: nx.Graph) -> dict[int, int]:
    """Exact reachability including source, with SCC-DAG bitsets for DiGraphs.

    Bit positions are ordinals of actual IDs, never node IDs. Each SCC shares
    its reachable set. Undirected graphs use connected-component sizes. No
    probability or diffusion outcomes enter this topology-only computation.
    """
    if graph.is_multigraph():
        raise TypeError("Use a simple processed graph")
    if not graph.is_directed():
        return {v: len(component) for component in nx.connected_components(graph) for v in component}
    ordinal = {v: i for i, v in enumerate(sorted(graph))}
    condensed = nx.condensation(graph)
    masks = {}
    for component in reversed(list(nx.topological_sort(condensed))):
        mask = sum(1 << ordinal[v] for v in condensed.nodes[component]["members"])
        for successor in condensed.successors(component):
            mask |= masks[successor]
        masks[component] = mask
    return {v: masks[component].bit_count() for v, component in condensed.graph["mapping"].items()}


def reachability_summary(counts: dict[int, int]) -> dict[str, Any]:
    """Distribution over all source nodes, retaining ties and all small sets."""
    if not counts:
        raise ValueError("A dataset must contain nodes")
    values = sorted(counts.values())
    def quantile(q: float) -> float:
        position = q * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return {"node_count": len(values), "min": min(values), "max": max(values),
            "mean": mean(values), "std_population": pstdev(values),
            "quantiles_linear": {str(q): quantile(q) for q in (0, .1, .25, .5, .75, .9, 1)},
            "histogram": [{"reachable_count": n, "source_node_count": frequency}
                          for n, frequency in sorted(Counter(values).items())]}


def sample_reachable_scenarios(counts: dict[int, int], dataset: str, master_seed: int,
                               per_stratum: int = 2, legacy_seed: int | None = None) -> tuple[list[dict], list[dict]]:
    """Sample within relative-to-maximum thirds; never split a tied value.

    Empty strata are explicit. Homogeneous datasets have one 'constant' stratum
    rather than fabricated low/medium/high ranks. Relative and graph fractions
    are both exported, since Wiki's maximum is much smaller than its node count.
    """
    if not counts or type(per_stratum) is not int or per_stratum < 1:
        raise ValueError("Invalid stratum sample size/universe")
    maximum, minimum = max(counts.values()), min(counts.values())
    groups: dict[str, list[int]] = {name: [] for name in ("low", "medium", "high", "constant")}
    for v, size in sorted(counts.items()):
        group = ("constant" if minimum == maximum else
                 "low" if size * 3 <= maximum else "medium" if size * 3 <= 2 * maximum else "high")
        groups[group].append(v)
    scenarios, strata = [], []
    for group, candidates in groups.items():
        seed = int.from_bytes(hashlib.sha256(f"pilot2-rumor-v1:{master_seed}:{dataset}:{group}".encode()).digest()[:8], "big")
        chosen = Random(seed).sample(candidates, min(per_stratum, len(candidates)))
        strata.append({"dataset": dataset, "stratum": group, "candidate_count": len(candidates),
                       "sampling_seed": seed, "sample_count": len(chosen),
                       "status": "sampled" if candidates else "empty_topological_stratum"})
        for index, v in enumerate(chosen):
            scenarios.append({"dataset": dataset, "scenario_id": f"{dataset}_{group}_{index}", "stratum": group,
                              "rumor_seeds": [v], "reachable_count": counts[v],
                              "reachable_excluding_seed": counts[v] - 1,
                              "reachable_fraction_of_graph": counts[v] / len(counts),
                              "reachable_fraction_of_maximum": counts[v] / maximum,
                              "sampling_seed": seed, "draw_index": index,
                              "role": "supplementary_low_reach" if group == "low" else "primary_candidate",
                              "selection_policy": "uniform_without_replacement_within_topology_stratum"})
    if legacy_seed is not None and not any(s["rumor_seeds"] == [legacy_seed] for s in scenarios):
        if legacy_seed not in counts:
            raise ValueError("Missing legacy rumor seed")
        scenarios.append({"dataset": dataset, "scenario_id": f"{dataset}_legacy_{legacy_seed}", "stratum": "legacy_low",
                          "rumor_seeds": [legacy_seed], "reachable_count": counts[legacy_seed],
                          "reachable_excluding_seed": counts[legacy_seed] - 1,
                          "reachable_fraction_of_graph": counts[legacy_seed] / len(counts),
                          "reachable_fraction_of_maximum": counts[legacy_seed] / maximum,
                          "sampling_seed": None, "draw_index": None, "role": "supplementary_legacy",
                          "selection_policy": "retained_from_prior_pilot_without_resampling"})
    return scenarios, strata


def observation_summary(counts: list[int], node_count: int, reachable_count: int | None = None) -> dict[str, Any]:
    """Pointwise approximate Student-t CI plus Wilson interval for no-spread.

    The t interval is descriptive conditional on fixed R/P, not a simultaneous
    or post-selection confidence statement. Zero empirical variance is flagged
    when topology permits more spread, rather than treated as proof of certainty.
    """
    if not counts or node_count < 1 or any(not 0 <= n <= node_count for n in counts):
        raise ValueError("Invalid observations")
    s, average = len(counts), mean(counts)
    sd = stdev(counts) if s > 1 else None
    se = sd / sqrt(s) if sd is not None else None
    half = float(t.ppf(.975, s - 1)) * se if se is not None else None
    no_spread = sum(v == 1 for v in counts) / s
    z = 1.959963984540054
    denominator = 1 + z*z/s
    center = (no_spread + z*z/(2*s)) / denominator
    radius = z * sqrt(no_spread*(1-no_spread)/s + z*z/(4*s*s)) / denominator
    return {"S": s, "rumor_mean": average, "rumor_std_population": pstdev(counts), "rumor_std_sample": sd,
            "rumor_SE": se, "ci95_low": average-half if half is not None else None,
            "ci95_high": average+half if half is not None else None,
            "ci95_half_width": half, "rumor_fraction": average / node_count,
            "reachable_fraction_activated": average / reachable_count if reachable_count else None,
            "no_spread_fraction": no_spread, "no_spread_wilson95_low": max(0.0, center-radius),
            "no_spread_wilson95_high": min(1.0, center+radius),
            "zero_variance_not_structurally_certain": sd == 0 and reachable_count not in (None, 1),
            "min_rumor_count": min(counts), "max_rumor_count": max(counts)}


def paired_differences(first: list[int], second: list[int]) -> dict[str, Any]:
    """CI of seed-aligned differences; does not assume shared edge outcomes."""
    if len(first) != len(second) or len(first) < 2:
        raise ValueError("Use matching independent simulation indices")
    differences = [a-b for a, b in zip(first, second)]
    se = stdev(differences) / sqrt(len(differences))
    half = float(t.ppf(.975, len(differences)-1)) * se
    delta = mean(differences)
    return {"mean_difference": delta, "SE_difference": se, "ci95_low": delta-half,
            "ci95_high": delta+half, "unresolved_at_pointwise_95": delta-half <= 0 <= delta+half}


def jaccard(first: list[int], second: list[int]) -> float:
    """Overlap of protector genotypes, including the shared empty-set case."""
    a, b = set(first), set(second)
    return len(a & b) / len(a | b) if a or b else 1.0


def ranking_diagnostics(observations: dict[str, list[int]]) -> tuple[list[str], list[dict]]:
    """Record descriptive order and pairwise uncertainty, without declaring a winner."""
    order = sorted(observations, key=lambda name: (mean(observations[name]), name))
    comparisons = [{"first": a, "second": b, **paired_differences(observations[a], observations[b])}
                   for a, b in combinations(sorted(observations), 2)]
    return order, comparisons


def choose_representative(control_rows: list[dict], scenarios: list[dict], *, min_fraction: float,
                          max_fraction: float, max_reachable_fraction: float) -> dict:
    """Pick using pooled No Intervention only, before looking at any algorithm.

    Prefer informative non-saturated regimes, lower p, then manifest order.
    A fallback is explicit when no cell meets the predeclared informativeness
    gate; it is never described as a validated main-experiment configuration.
    """
    candidates = {s["scenario_id"]: i for i, s in enumerate(scenarios) if s["role"] == "primary_candidate"}
    rows = [r for r in control_rows if r["scenario_id"] in candidates]
    if not rows:
        raise ValueError("No primary topology scenario")
    qualifying = [r for r in rows if min_fraction <= r["rumor_fraction"] <= max_fraction
                  and r["reachable_fraction_activated"] <= max_reachable_fraction]
    if qualifying:
        row = min(qualifying, key=lambda r: (r["p"], candidates[r["scenario_id"]]))
        return {**row, "calibration_admission": "informative_control_only"}
    row = min(rows, key=lambda r: (-r["rumor_fraction"], r["p"], candidates[r["scenario_id"]]))
    return {**row, "calibration_admission": "fallback_no_cell_met_control_gate"}
