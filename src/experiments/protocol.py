"""Pilot planning and descriptive diagnostics; no diffusion/optimizer changes."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
from math import ceil, sqrt
from random import Random
from statistics import mean, stdev
from typing import Any

import networkx as nx

from .config import ALGORITHMS, ExperimentConfig
from .runner import ExperimentLimitError, preflight


def fixed_rumor_scenario(graph: nx.Graph, dataset: str, master_seed: int, count: int) -> dict[str, Any]:
    """Uniformly sample actual integer IDs once; never resample using outcomes."""
    if type(count) is not int or not 0 <= count <= len(graph):
        raise ValueError("Invalid rumor seed count")
    seed = int.from_bytes(hashlib.sha256(
        f"pilot-protocol-rumor-v1:{master_seed}:{dataset}".encode()).digest()[:8], "big")
    nodes = sorted(Random(seed).sample(sorted(graph), count))
    reachable = set(nodes)
    for node in nodes:
        reachable.update(nx.descendants(graph, node) if graph.is_directed()
                         else nx.node_connected_component(graph, node))
    return {"dataset": dataset, "rumor_seeds": nodes, "sampling_seed": seed,
            "sampling_policy": "uniform_without_replacement_from_sorted_actual_node_ids",
            "scope": "fixed_across_p_methods_and_independent_algorithm_runs",
            "reachable_node_count": len(reachable), "node_count": len(graph),
            "seed_degrees": {str(v): graph.out_degree(v) if graph.is_directed() else graph.degree(v) for v in nodes}}


def plan_methods(graph: nx.Graph, values: dict[str, Any]) -> tuple[ExperimentConfig, list[dict[str, Any]]]:
    """Check all seven separately; only budget rejections become explicit skips.

    Invalid inputs propagate. Full Greedy is never silently replaced with a
    restricted search. All allowed methods still use the unmodified runner.
    """
    template = deepcopy(values)
    template.pop("algorithm", None)
    template.pop("skipped_algorithms", None)
    allowed, skipped, estimates = [], {}, []
    for name in ALGORITHMS:
        config = ExperimentConfig.from_dict({**template, "algorithms": [name]})
        c = config.to_dict()
        # Obtain exact/upper work counts without changing the real limits.
        unbounded = deepcopy(c)
        unbounded["limits"] = {key: 10**30 for key in c["limits"]}
        cost = preflight(graph, tuple(c["rumor_seeds"]), unbounded)[name]
        try:
            preflight(graph, tuple(c["rumor_seeds"]), c)
        except ExperimentLimitError as error:
            status, reason = "skipped", str(error)
            skipped[name] = reason
        else:
            status, reason = "planned", None
            allowed.append(name)
        estimates.append({"algorithm": name, "status": status, "reason": reason, **cost,
                          "final_evaluation_count": int(status == "planned"),
                          "final_cic_simulations": c["S_eval"] if status == "planned" else 0})
    return ExperimentConfig.from_dict({**template, "algorithms": allowed,
                                       "skipped_algorithms": skipped}), estimates


def spread_diagnostics(counts: list[int], *, node_count: int, rumor_count: int,
                       reachable_count: int, low_fraction: float, saturation_fraction: float) -> dict[str, Any]:
    """Classify control spread using thresholds declared before observations."""
    if not counts or not 0 < node_count or not 0 <= rumor_count <= reachable_count <= node_count:
        raise ValueError("Invalid control observations/universe")
    average = mean(counts)
    return {"observation_count": len(counts), "control_rumor_mean": average,
            "mean_fraction_of_graph": average / node_count,
            "mean_fraction_of_reachable": average / reachable_count if reachable_count else None,
            "additional_mean_fraction": (average - rumor_count) / node_count,
            "no_spread_fraction": sum(v == rumor_count for v in counts) / len(counts),
            "near_saturation_observation_fraction": sum(v >= saturation_fraction * node_count for v in counts) / len(counts),
            "low_spread": (average - rumor_count) / node_count < low_fraction,
            "near_graph_saturation": average / node_count >= saturation_fraction,
            "min_count": min(counts), "max_count": max(counts),
            "sample_std": stdev(counts) if len(counts) > 1 else None,
            "standard_error": stdev(counts) / sqrt(len(counts)) if len(counts) > 1 else None}


def precision_diagnostics(counts: list[int], node_count: int, prefixes: list[int],
                          opt_fraction: float, eval_fraction: float) -> list[dict[str, Any]]:
    """Nested held-out prefixes, not independent batches or extra fitness runs.

    Required-S figures are plug-in variance estimates, not measured guarantees.
    Full held-out mean is itself noisy and is not a ground-truth expectation.
    """
    if not counts or node_count <= 0 or min(opt_fraction, eval_fraction) <= 0:
        raise ValueError("Invalid precision configuration")
    full = mean(counts)
    result = []
    for s in prefixes:
        if type(s) is not int or s < 1:
            raise ValueError("Invalid prefix size")
        if s > len(counts):
            continue
        values = counts[:s]
        sd = stdev(values) if s > 1 else None
        result.append({"S": s, "mean": mean(values), "sample_std": sd,
                       "standard_error": sd / sqrt(s) if sd is not None else None,
                       "difference_from_full_heldout_mean": mean(values) - full,
                       "required_S_opt_plugin": max(2, ceil((sd / (opt_fraction * node_count))**2)) if sd is not None else None,
                       "required_S_eval_plugin": max(2, ceil((sd / (eval_fraction * node_count))**2)) if sd is not None else None})
    return result


def projected_runtime(smoke_summary: dict[str, Any], estimates: list[dict[str, Any]], safety_factor: float) -> float:
    """Conservative smoke-rate projection; not a measured runtime guarantee."""
    if safety_factor < 1:
        raise ValueError("Runtime safety factor must be >= 1")
    rates = []
    for row in smoke_summary["results"]:
        for seconds, simulations in ((row["optimization_evaluator_seconds"], row["optimization_cic_simulations"]),
                                      (row["final_evaluation_runtime_seconds"], row["final_cic_simulations"])):
            if simulations:
                rates.append(seconds / simulations)
    count = sum(row["optimization_cic_simulation_upper_bound"] + row["final_cic_simulations"]
                for row in estimates if row["status"] == "planned")
    return safety_factor * (max(rates, default=0.0) * count
                            + smoke_summary["timings"]["total_experiment_runtime_seconds"])
