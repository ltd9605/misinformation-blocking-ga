"""Unified selection, independent evaluation and atomic experiment exports."""

from copy import deepcopy
import csv
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import json
from math import comb
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

import networkx as nx

from src.algorithms import (
    estimate_greedy_cost, select_candidate_restricted_greedy, select_degree,
    select_genetic_algorithm, select_greedy, select_pagerank, select_random,
)
from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.evaluation import MonteCarloResult, evaluate_cic
from .config import ExperimentConfig, ExperimentConfigError, OPTIMIZERS
from .metadata import environment_metadata
from .metrics import final_metrics
from .seeds import ExperimentSeedPlan, make_experiment_seed_plan


class ExperimentLimitError(ValueError):
    """The declared work budget prevents an optimization from running."""


@dataclass(frozen=True)
class ExperimentResult:
    output_directory: Path
    rows: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    metadata: dict[str, Any]


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_plain(value), sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def _mc_summary(estimate: MonteCarloResult) -> dict[str, Any]:
    return {key: value for key, value in vars(estimate).items() if key != "raw_results"}


def resolve_rumor(graph: nx.Graph, c: dict[str, Any], seeds: ExperimentSeedPlan) -> tuple[int, ...]:
    """Resolve once per comparison, before selecting any protector set."""
    if "rumor_seeds" in c:
        rumor = c["rumor_seeds"]
    else:
        policy = c["rumor_seed_policy"]
        if policy["count"] > len(graph):
            raise ExperimentConfigError("Rumor count exceeds graph size")
        seed = seeds.rumor_seed_fixed if policy["scope"] == "fixed" else seeds.rumor_seed_per_run
        rumor = Random(seed).sample(sorted(graph), policy["count"])
    if set(rumor).difference(graph):
        raise ExperimentConfigError("Rumor seeds do not exist in processed graph")
    if c["k"] > len(graph) - len(rumor):
        raise ExperimentConfigError("k exceeds eligible non-rumor node count")
    return tuple(sorted(rumor))


def preflight(graph: nx.Graph, rumor: tuple[int, ...], c: dict[str, Any]) -> dict[str, Any]:
    """Reject every excessive optimizer before any selection/evaluator call."""
    m, k, s = len(graph) - len(rumor), c["k"], c["S_opt"]
    result = {}
    for algorithm in c["algorithms"]:
        calls = 0
        extra: dict[str, Any] = {}
        if algorithm == "full_greedy":
            calls = estimate_greedy_cost(m, k, s).evaluation_count
            extra["candidate_count"] = m
        elif algorithm == "candidate_restricted_greedy":
            restriction = c["candidate_restriction"]
            if restriction["method"] == "degree":
                size = restriction["size"]
                if size > m:
                    raise ExperimentConfigError("Restricted candidate size exceeds eligible nodes")
            else:
                pool = set(restriction["nodes"])
                if pool.difference(graph) or pool & set(rumor):
                    raise ExperimentConfigError("Explicit candidate pool contains missing or rumor nodes")
                size = len(pool)
            calls = estimate_greedy_cost(size, k, s).evaluation_count
            extra["candidate_count"] = size
        elif algorithm == "genetic_algorithm":
            ga = c["ga_parameters"]
            upper = ga["population_size"] + ga["max_generations"] * (ga["population_size"] - ga["elitism_count"])
            calls = min(upper, comb(m, k)) if ga["cache_fitness"] else upper
            extra.update(uncached_evaluation_upper_bound=upper, cache_enabled=ga["cache_fitness"])
        if algorithm in OPTIMIZERS:
            limits = c["limits"]
            if calls > limits["max_optimization_evaluations"] or calls * s > limits["max_optimization_cic_simulations"]:
                raise ExperimentLimitError(f"{algorithm}: estimated {calls} evaluations/{calls*s} CIC simulations exceed optimization limits")
            if algorithm == "full_greedy" and (
                calls > limits["max_full_greedy_evaluations"] or calls * s > limits["max_full_greedy_cic_simulations"]
            ):
                raise ExperimentLimitError(f"Full Greedy blocked: {calls} evaluations/{calls*s} CIC simulations exceed explicit Full Greedy limits")
        result[algorithm] = {"optimization_evaluation_upper_bound": calls,
                             "optimization_cic_simulation_upper_bound": calls * s,
                             "runtime_prediction_seconds": None, **extra}
    return result


def _select(graph: nx.Graph, rumor: tuple[int, ...], c: dict[str, Any], algorithm: str,
            seeds: ExperimentSeedPlan) -> tuple[frozenset[int], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Dispatch unchanged APIs; pool construction is included in selection time."""
    details: dict[str, Any] = {}
    convergence: list[dict[str, Any]] = []
    count = simulations = 0
    evaluator_time = pool_time = 0.0
    training_score = None
    selected = None
    if algorithm == "no_intervention":
        return frozenset(), {"selection_runtime_seconds": 0.0, "optimization_evaluation_count": 0,
                             "optimization_cic_simulations": 0, "optimization_evaluator_seconds": 0.0,
                             "candidate_pool_selection_seconds": 0.0,
                             "optimization_best_estimated_fitness": None}, details, convergence
    started = perf_counter()
    if algorithm == "random":
        protector = select_random(graph, rumor, c["k"], random_seed=seeds.random_selection_seed)
        details["random_selection_seed"] = seeds.random_selection_seed
    elif algorithm == "degree":
        protector = select_degree(graph, rumor, c["k"])
    elif algorithm == "pagerank":
        protector = select_pagerank(graph, rumor, c["k"], **c["pagerank_parameters"])
    elif algorithm in ("full_greedy", "candidate_restricted_greedy"):
        args = (graph, rumor, c["k"], c["p"], c["S_opt"])
        kwargs = {"base_random_seed": seeds.optimization_base_random_seed, "tie_breaking": c["tie_breaking"]}
        if algorithm == "full_greedy":
            selected = select_greedy(*args, **kwargs)
        else:
            pool_started = perf_counter()
            restriction = c["candidate_restriction"]
            pool = (select_degree(graph, rumor, restriction["size"]) if restriction["method"] == "degree"
                    else frozenset(restriction["nodes"]))
            pool_time = perf_counter() - pool_started
            selected = select_candidate_restricted_greedy(*args, candidate_nodes=pool, **kwargs)
        protector = selected.protector_nodes
        count, simulations = selected.evaluation_count, selected.cic_simulation_count
        evaluator_time, training_score = selected.evaluation_runtime_seconds, selected.final_mean_rumor_count
    else:
        selected = select_genetic_algorithm(
            graph, rumor, c["k"], c["p"], c["S_opt"], **c["ga_parameters"],
            random_seed=seeds.ga_random_seed, fitness_base_random_seed=seeds.optimization_base_random_seed,
            tie_breaking=c["tie_breaking"],
        )
        protector = selected.best_protector_nodes
        count, simulations = selected.evaluation_count, selected.cic_simulation_count
        evaluator_time, training_score = selected.evaluator_runtime_seconds, selected.best_estimated_fitness
    elapsed = perf_counter() - started
    if selected is not None:
        details = _plain(selected)
    if algorithm == "genetic_algorithm":
        for generation in selected.history:
            row = asdict(generation)
            row.pop("population")
            row.pop("fitness_values")
            row["best_protector_nodes"] = sorted(generation.best_protector_nodes)
            row["population_size"] = len(generation.population)
            convergence.append({"algorithm": algorithm, **row})
    if len(protector) != c["k"] or set(protector).difference(graph) or set(protector) & set(rumor):
        raise RuntimeError(f"{algorithm} violated protector constraints")
    return protector, {
        "selection_runtime_seconds": elapsed, "optimization_evaluation_count": count,
        "optimization_cic_simulations": simulations, "optimization_evaluator_seconds": evaluator_time,
        "candidate_pool_selection_seconds": pool_time, "optimization_best_estimated_fitness": training_score,
    }, details, convergence


def _protected_output(directory: Path, source: Path) -> None:
    for protected in ((PROJECT_ROOT / "data").resolve(), source.resolve()):
        resolved = directory.resolve()
        if resolved == protected or resolved.is_relative_to(protected):
            raise ExperimentConfigError("Experiment output must not write into dataset directories")


def run_experiment(config: ExperimentConfig) -> ExperimentResult:
    """Run one independent index and a uniform comparison, publishing atomically.

    Every P is finalized before any final evaluation. The control is evaluated
    once and always exported as the first row. Empty-P methods reuse it, report
    zero additional final calls/runtime, and reference the control evaluation ID.
    Other methods each get a fresh evaluator call on the same final seed block.
    Final metrics never use selection/optimization scores. No preprocessing runs.

    Total time runs from function entry through primary artifact writes, but
    excludes configuration parsing and the last metadata/summary writes/rename.
    Those small manifest operations cannot include their own final timings.
    """
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    # Revalidate even if a caller modified an internal config dictionary.
    config = ExperimentConfig.from_dict(config.to_dict(), source_path=config.source_path)
    c = config.to_dict()
    source, destination = Path(c["processed_directory"]), config.run_directory
    _protected_output(destination, source)
    if destination.exists():
        raise FileExistsError(f"Experiment directory already exists; choose another output root/run: {destination}")
    load_started = perf_counter()
    graph = load_processed_graph(source)
    dataset_metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    if dataset_metadata.get("dataset") != c["dataset"]:
        raise ExperimentConfigError("Dataset label does not match processed metadata")
    loading_time = perf_counter() - load_started
    source_hashes = {name: sha256_file(source / name) for name in ("nodes.csv", "edges.csv", "metadata.json")}
    before = deepcopy(graph)
    nx.freeze(graph)
    seeds = make_experiment_seed_plan(c["random_seed"], c["independent_run_index"], c["seed_block_size"])
    rumor = resolve_rumor(graph, c, seeds)
    estimates = preflight(graph, rumor, c)
    provenance = environment_metadata()
    selections = {}
    details = {}
    convergence = []
    # Complete every selection before exposing any independent evaluation result.
    for algorithm in c["algorithms"]:
        protector, timing, detail, history = _select(graph, rumor, c, algorithm, seeds)
        selections[algorithm] = (protector, timing)
        details[algorithm] = detail
        convergence.extend(history)
        if not nx.utils.graphs_equal(graph, before):
            raise RuntimeError(f"{algorithm} modified the input graph")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".experiment-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        raw_stream = None
        raw_writer = None
        if c["save_raw_observations"]:
            raw_stream = (stage / "raw_observations.csv").open("w", encoding="utf-8", newline="")
            raw_writer = csv.DictWriter(raw_stream, fieldnames=("evaluation_id", "algorithm", "simulation_index",
                                                               "random_seed", "rumor_count", "protector_count",
                                                               "inactive_count", "steps"), lineterminator="\n")
            raw_writer.writeheader()
        rows = []
        final_summaries = {}
        try:
            control = evaluate_cic(graph, rumor, [], c["p"], c["S_eval"],
                                   base_random_seed=seeds.final_base_random_seed, tie_breaking=c["tie_breaking"])
            for algorithm in c["algorithms"]:
                protector, timing = selections[algorithm]
                owns_call = algorithm == "no_intervention" or bool(protector)
                estimate = (evaluate_cic(graph, rumor, protector, c["p"], c["S_eval"],
                                         base_random_seed=seeds.final_base_random_seed, tie_breaking=c["tie_breaking"])
                            if protector else control)
                evaluation_id = algorithm if protector else "no_intervention"
                if raw_writer is not None and owns_call:
                    for observation in estimate.raw_results:
                        raw_writer.writerow({"evaluation_id": evaluation_id, "algorithm": algorithm, **asdict(observation)})
                rows.append({
                    "dataset": c["dataset"], "independent_run_index": c["independent_run_index"],
                    "algorithm": algorithm, "rumor_seeds": list(rumor), "protector_seeds": sorted(protector),
                    "k": c["k"], "selected_protector_count": len(protector), "p": c["p"],
                    "tie_breaking": c["tie_breaking"], "S_opt": c["S_opt"], "S_eval": c["S_eval"],
                    "random_seed": c["random_seed"], "optimization_base_random_seed": seeds.optimization_base_random_seed,
                    "final_base_random_seed": seeds.final_base_random_seed, **timing,
                    "final_evaluation_id": evaluation_id, "reused_control_evaluation": not owns_call,
                    "final_evaluation_count": int(owns_call),
                    "final_cic_simulations": c["S_eval"] if owns_call else 0,
                    "final_evaluation_runtime_seconds": estimate.runtime_seconds if owns_call else 0.0,
                    **final_metrics(estimate, control),
                })
                final_summaries[algorithm] = _mc_summary(estimate)
            if not nx.utils.graphs_equal(graph, before):
                raise RuntimeError("Final evaluation modified the graph")
            if source_hashes != {name: sha256_file(source / name) for name in source_hashes}:
                raise RuntimeError("Processed dataset files changed during experiment")
        finally:
            if raw_stream is not None:
                raw_stream.close()
        export_started = perf_counter()
        _write_json(stage / "config.json", c)
        _write_json(stage / "preflight.json", estimates)
        _write_json(stage / "selection_details.json", details)
        _write_csv(stage / "results.csv", rows)
        if convergence:
            _write_csv(stage / "convergence.csv", convergence)
        primary_write_time = perf_counter() - export_started
        total = perf_counter() - started
        metadata = {
            "schema_version": 1, "declared_purpose": c["purpose"], "config_fingerprint": config.fingerprint,
            "started_at_utc": started_at,
            "config_source_path": str(config.source_path) if config.source_path else None,
            "resolved_rumor_seeds": list(rumor), "seed_plan": asdict(seeds),
            "seed_intervals": {"optimization_inclusive": [seeds.optimization_base_random_seed, seeds.optimization_base_random_seed + c["S_opt"] - 1],
                               "final_inclusive": [seeds.final_base_random_seed, seeds.final_base_random_seed + c["S_eval"] - 1]},
            "environment": provenance, "dataset_metadata": dataset_metadata,
            "processed_source_directory": source.as_posix(), "processed_source_sha256": source_hashes,
            "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
            "graph_unchanged": True, "processed_artifacts_unchanged": True,
            "timings": {
                "graph_loading_seconds": loading_time, "preprocessing_seconds": 0.0,
                "selection_optimization_seconds": sum(row["selection_runtime_seconds"] for row in rows),
                "final_evaluation_seconds": sum(row["final_evaluation_runtime_seconds"] for row in rows),
                "primary_artifact_write_seconds": primary_write_time,
                "total_experiment_runtime_seconds": total,
            },
            "timing_scope": {
                "loading": "load_processed_graph plus reading provenance metadata; no preprocessing",
                "selection": "method call including candidate pool construction and optimization MC; excludes loading/export",
                "final_evaluation": "evaluator-reported runtime; shared empty-P control charged once to no_intervention",
                "total": "run_experiment entry through primary artifact writes; excludes config parsing, final metadata/summary writes and rename",
            },
            "protocol": {
                "all_selections_before_final_evaluation": True,
                "same_final_seed_schedule_for_all_methods": True,
                "optimization_and_final_seed_intervals_disjoint": True,
                "GA_suggested_holdout_base_overridden_by_runner_final_block": True,
                "edge_level_common_random_outcomes_guaranteed": False,
                "raw_observation_scope": "final/control only" if c["save_raw_observations"] else "not saved",
                "SE": "sample std / sqrt(S_eval); null for S_eval=1",
                "zero_control_mean_reduction": "undefined/null; negative reductions are not clipped",
            },
            "artifact_sha256": {p.name: sha256_file(p) for p in sorted(stage.iterdir()) if p.is_file()},
        }
        metadata["timings"]["orchestration_other_seconds"] = max(
            0.0, total - loading_time - metadata["timings"]["selection_optimization_seconds"]
            - metadata["timings"]["final_evaluation_seconds"] - primary_write_time)
        summary = {
            "dataset": c["dataset"], "declared_purpose": c["purpose"],
            "independent_run_index": c["independent_run_index"], "resolved_rumor_seeds": list(rumor),
            "control": _mc_summary(control), "results": rows, "final_evaluations": final_summaries,
            "total_optimization_evaluations": sum(row["optimization_evaluation_count"] for row in rows),
            "total_final_evaluations": sum(row["final_evaluation_count"] for row in rows),
            "total_cic_simulations": sum(row["optimization_cic_simulations"] + row["final_cic_simulations"] for row in rows),
            "timings": metadata["timings"],
        }
        _write_json(stage / "metadata.json", metadata)
        _write_json(stage / "summary.json", summary)
        if destination.exists():
            raise FileExistsError(f"Output appeared during execution: {destination}")
        stage.rename(destination)
    return ExperimentResult(destination, tuple(rows), summary, metadata)
