"""Milestone 5 smoke pilots, not an experiment runner or algorithm comparison."""

import argparse
import csv
from dataclasses import asdict, is_dataclass
from itertools import combinations
import json
from math import comb
import os
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

import networkx as nx

from src.algorithms import make_seed_plan, select_genetic_algorithm
from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.diffusion.cic import _node_sort_key
from src.evaluation import evaluate_cic


DEFAULT_CONFIG = PROJECT_ROOT / "experiments/configs/ga_pilot_email.json"


def _plain(value: Any) -> Any:
    """Serialize dataclasses/immutable sets in the integer-labeled pilot cases."""
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value, key=_node_sort_key)]
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _data_hashes() -> dict[str, str]:
    return {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p)
            for p in sorted((PROJECT_ROOT / "data").rglob("*")) if p.is_file()}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_plain(value), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _run_case(name: str, graph: nx.Graph, config: dict[str, Any], output: Path,
              *, toy_oracle: bool = False) -> dict[str, Any]:
    """Optimize/replay first; evaluate the frozen solution once on fresh seeds."""
    parameters = dict(config)
    s_eval = parameters.pop("independent_evaluation_simulations")
    parameters.pop("dataset")
    m = len(graph) - len(set(parameters["rumor_seeds"]))
    n, g, e, k = (parameters[key] for key in ("population_size", "max_generations", "elitism_count", "k"))
    upper = n + g * (n - e)
    seeds = make_seed_plan(parameters["random_seed"], parameters["number_of_simulations"],
                           parameters.get("fitness_base_random_seed"))
    preflight = {
        "eligible_nodes": m, "genotype_space_size": comb(m, k),
        "uncached_evaluation_upper_bound": upper,
        "cached_evaluation_upper_bound": min(upper, comb(m, k)),
        "uncached_CIC_simulation_upper_bound": upper * parameters["number_of_simulations"],
        "initial_generation_logged": True, "seed_plan": _plain(seeds),
        "independent_evaluation_simulations": s_eval,
        "runtime_prediction_seconds": None,
    }
    _write_json(output / f"{name}_preflight.json", preflight)
    result = select_genetic_algorithm(graph, **parameters)
    replay = select_genetic_algorithm(graph, **parameters)
    if result != replay:
        raise RuntimeError(f"GA replay differs: {name}")
    best = result.best_protector_nodes
    # This direct evaluator call bypasses the now-finished GA's local cache.
    # Its disjoint seeds and score never influence optimizer selection.
    independent = evaluate_cic(
        graph, parameters["rumor_seeds"], best, parameters["propagation_probability"], s_eval,
        base_random_seed=result.seeds.independent_evaluation_base_random_seed,
        tie_breaking=parameters["tie_breaking"],
    )
    oracle = None
    oracle_calls = 0
    if toy_oracle:
        if len(graph) > 6 or parameters["propagation_probability"] != 1:
            raise ValueError("Exhaustive verification is limited to tiny deterministic toy graphs")
        eligible = sorted(set(graph) - set(parameters["rumor_seeds"]))
        scores = []
        for protector in combinations(eligible, k):
            measured = evaluate_cic(graph, parameters["rumor_seeds"], protector, 1, 1,
                                    base_random_seed=result.seeds.independent_evaluation_base_random_seed + s_eval,
                                    tie_breaking=parameters["tie_breaking"])
            oracle_calls += 1
            scores.append((measured.mean_rumor_count, protector))
        optimum, optimum_p = min(scores)
        oracle = {"verified_optimum": optimum, "one_optimal_P": list(optimum_p),
                  "ga_reached_optimum": independent.mean_rumor_count == optimum,
                  "evaluation_count": oracle_calls, "CIC_simulation_count": oracle_calls,
                  "used_for_GA_selection": False}
    directory = output / name
    directory.mkdir(exist_ok=True)
    with (directory / "convergence.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ("generation", "best_fitness", "best_so_far_fitness", "mean_fitness", "worst_fitness",
                  "best_protector_nodes", "population_size", "unique_individuals", "elite_count_carried",
                  "evaluations_this_generation", "cumulative_evaluations", "cache_hits_this_generation",
                  "cumulative_cache_hits", "elapsed_optimization_seconds")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in result.history:
            record = asdict(item)
            record.pop("population")
            record.pop("fitness_values")
            record["best_protector_nodes"] = json.dumps(sorted(item.best_protector_nodes))
            record["population_size"] = len(item.population)
            writer.writerow(record)
    with (directory / "fitness_evaluations.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ("evaluation_index", "generation", "protector_nodes", "mean_rumor_count", "std_rumor_count",
                  "mean_protector_count", "mean_inactive_count", "runtime_seconds", "base_random_seed", "S_opt")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in result.fitness_evaluations:
            record = asdict(item)
            record["protector_nodes"] = json.dumps(sorted(item.protector_nodes))
            record["base_random_seed"] = result.seeds.fitness_base_random_seed
            record["S_opt"] = parameters["number_of_simulations"]
            writer.writerow(record)
    _write_json(directory / "convergence.json", result.history)
    case = {
        "name": name, "config": config, "preflight": preflight,
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "optimization": _plain(result), "replay_runtime_seconds": replay.optimization_runtime_seconds,
        "replay_evaluation_count": replay.evaluation_count,
        "repeatability_verified_excluding_runtime": True,
        "independent_evaluation": _plain(independent), "independent_evaluation_count": 1,
        "independent_evaluation_used_for_selection": False,
        "toy_oracle": oracle,
        "total_evaluations_including_replay_holdout_oracle": result.evaluation_count + replay.evaluation_count + 1 + oracle_calls,
        "total_CIC_simulations_including_replay_holdout_oracle": result.cic_simulation_count + replay.cic_simulation_count + s_eval + oracle_calls,
    }
    _write_json(directory / "report.json", case)
    print(f"{name}: P={sorted(best)}, optimization={result.best_estimated_fitness:.6f}, "
          f"independent={independent.mean_rumor_count:.6f}, calls={result.evaluation_count}, "
          f"cache_hits={result.cache_hit_count}, optimization_time={result.optimization_runtime_seconds:.6f}s",
          flush=True)
    return case


def _plot(cases: list[dict[str, Any]], path: Path) -> None:
    """Plot fixed-seed optimization histories; independent scores stay separate."""
    with TemporaryDirectory(prefix="ga-mpl-") as temporary:
        previous = os.environ.get("MPLCONFIGDIR")
        os.environ["MPLCONFIGDIR"] = temporary
        try:
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib import pyplot as plt
            fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
            for ax, case in zip(axes.flat, cases):
                history = case["optimization"]["history"]
                x = [row["generation"] for row in history]
                ax.plot(x, [row["best_fitness"] for row in history], marker="o", label="generation best")
                ax.plot(x, [row["mean_fitness"] for row in history], marker="o", label="population mean")
                ax.plot(x, [row["best_so_far_fitness"] for row in history], linestyle="--", label="best so far")
                ax.set_title(case["name"])
                ax.set_xlabel("generation (0 = initialization)")
                ax.set_ylabel("fixed-seed mean rumor fitness")
                ax.grid(alpha=0.25)
                ax.legend()
            fig.suptitle("GA PILOT ONLY - optimization histories; held-out scores are in JSON")
            fig.savefig(path, dpi=160)
            plt.close(fig)
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = previous


def main() -> int:
    """Run three toy cases followed by one light email GA; no other datasets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "results/pilots/genetic_algorithm")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["dataset"] != "email-Eu-core":
        raise ValueError("This smoke pilot supports only email-Eu-core, not Facebook/Wiki-Vote")
    for key, lower, upper in (("population_size", 1, 20), ("max_generations", 0, 10),
                               ("number_of_simulations", 1, 50), ("independent_evaluation_simulations", 1, 200)):
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise ValueError(f"Smoke pilot requires {lower} <= {key} <= {upper}")
    output = args.output_dir
    protected = (PROJECT_ROOT / "data").resolve()
    destinations = [output, output / "report.json", output / "config.json", output / "convergence.png"]
    for name in ("directed_chain", "undirected_chain", "two_branches", "email-Eu-core"):
        destinations += [output / name, output / f"{name}_preflight.json"]
        destinations += [output / name / file for file in ("report.json", "convergence.csv", "convergence.json", "fitness_evaluations.csv")]
    for destination in destinations:
        resolved = destination.resolve()
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("GA pilot output must not overwrite raw/processed datasets")
    before = _data_hashes()
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "config.json", config)
    cases = []
    examples = (
        ("directed_chain", nx.DiGraph([(0, 1), (1, 2), (2, 3)]), 1),
        ("undirected_chain", nx.path_graph(5), 1),
        ("two_branches", nx.DiGraph([(0, 10), (10, 1), (1, 2), (0, 20), (20, 30)]), 2),
    )
    for name, graph, k in examples:
        toy = dict(config, dataset=name, k=k, propagation_probability=1,
                   population_size=8, max_generations=4, number_of_simulations=3,
                   independent_evaluation_simulations=5)
        cases.append(_run_case(name, graph, toy, output, toy_oracle=True))
    graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
    cases.append(_run_case("email-Eu-core", graph, config, output))
    _plot(cases, output / "convergence.png")
    after = _data_hashes()
    if before != after:
        raise RuntimeError("Raw/processed datasets changed during the GA pilot")
    report = {
        "purpose": "genetic_algorithm_implementation_smoke_pilot_only", "official_thesis_result": False,
        "fitness_policy": "fixed_seed_schedule_local_cache_elite_fitness_preserved",
        "user_confirmed_fitness_policy": True,
        "cases": cases,
        "total_evaluations_including_replays_holdouts_toy_oracles": sum(case["total_evaluations_including_replay_holdout_oracle"] for case in cases),
        "total_CIC_simulations_including_replays_holdouts_toy_oracles": sum(case["total_CIC_simulations_including_replay_holdout_oracle"] for case in cases),
        "environment": {"python": platform.python_version(), "networkx": nx.__version__,
                        "platform": platform.platform(), "machine": platform.machine()},
        "data_sha256_before": before, "data_sha256_after": after, "source_data_unchanged": True,
        "limitations": [
            "Small N/G/S_opt/S_eval test execution only; not the official settings from a parameter study.",
            "A fixed noisy objective can be overfit; cache hits/elite carries add no independent samples.",
            "Independent scores are evaluated after selection on a disjoint seed interval and never used for selection.",
            "No global-optimum guarantee; toy oracle results are verification only and never initialize the GA.",
            "No baseline comparison, no Facebook/Wiki-Vote benchmark and no experiment runner.",
            "Per-generation population snapshots cost memory proportional to G*N*k.",
        ],
    }
    _write_json(output / "report.json", report)
    print(f"PILOT ONLY. Convergence CSV/JSON and reports saved to {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
