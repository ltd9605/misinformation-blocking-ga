"""Full Greedy toy checks and a labeled Candidate-Restricted Greedy email pilot.

This performs no Full Greedy dataset benchmark. Outputs are pilot diagnostics.
"""

import argparse
import csv
import json
from pathlib import Path
import platform
from time import perf_counter
from typing import Any

import networkx as nx

from src.algorithms import (
    GreedyResult, estimate_greedy_cost, select_candidate_restricted_greedy,
    select_degree, select_greedy,
)
from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from dataclasses import asdict


DEFAULT_CONFIG = PROJECT_ROOT / "experiments/configs/greedy_email.json"
OUTPUT_NAMES = ("config.json", "preflight.json", "report.json", "steps.csv", "trials.csv")


def _data_hashes() -> dict[str, str]:
    return {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p)
            for p in sorted((PROJECT_ROOT / "data").rglob("*")) if p.is_file()}


def _result_dict(result: GreedyResult) -> dict[str, Any]:
    """Serialize integer-labeled pilot histories, including every trial score."""
    return {
        "algorithm": result.algorithm,
        "protector_nodes": sorted(result.protector_nodes), "selection_order": list(result.selection_order),
        "candidate_nodes": sorted(result.candidate_nodes),
        "number_of_simulations": result.number_of_simulations,
        "base_random_seed": result.base_random_seed, "tie_breaking": result.tie_breaking,
        "evaluation_count": result.evaluation_count, "cic_simulation_count": result.cic_simulation_count,
        "final_mean_rumor_count": result.final_mean_rumor_count,
        "runtime_seconds": result.runtime_seconds,
        "evaluation_runtime_seconds": result.evaluation_runtime_seconds,
        "steps": [{
            "step_index": step.step_index, "selected_node": step.selected_node,
            "protector_nodes": sorted(step.protector_nodes),
            "mean_rumor_count": step.mean_rumor_count, "std_rumor_count": step.std_rumor_count,
            "evaluation_count": step.evaluation_count,
            "candidate_evaluations": [asdict(trial) for trial in step.candidate_evaluations],
        } for step in result.steps],
    }


def _check_small_graphs() -> list[dict[str, Any]]:
    """Check Full Greedy decisions and work counts before any dataset search."""
    examples = (
        ("directed_chain", nx.DiGraph([(0, 1), (1, 2), (2, 3)]), [1, 2], [1, 1]),
        ("undirected_chain", nx.path_graph(4), [1, 2], [1, 1]),
        ("two_branches", nx.DiGraph([(0, 10), (10, 1), (1, 2), (0, 20), (20, 30)]), [10, 20], [3, 1]),
    )
    checks = []
    for name, graph, expected_order, expected_scores in examples:
        result = select_greedy(graph, [0], 2, 1, 3,
                               base_random_seed=42, tie_breaking="protector-priority")
        expected_cost = estimate_greedy_cost(len(graph) - 1, 2, 3)
        if (
            list(result.selection_order) != expected_order
            or [step.mean_rumor_count for step in result.steps] != expected_scores
            or result.evaluation_count != expected_cost.evaluation_count
        ):
            raise RuntimeError(f"Full Greedy hand check failed: {name}")
        checks.append({
            "name": name, "passed": True,
            "graph": {"directed": graph.is_directed(), "nodes": sorted(graph), "edges": sorted(graph.edges())},
            "config": {"rumor_seeds": [0], "protector_budget": 2, "propagation_probability": 1,
                       "number_of_simulations": 3, "base_random_seed": 42, "tie_breaking": "protector-priority"},
            "expected_selection_order": expected_order, "expected_step_means": expected_scores,
            "result": _result_dict(result),
        })
        print(f"PASS Full Greedy {name}: order={expected_order}, means={expected_scores}, "
              f"evaluations={result.evaluation_count}", flush=True)
    return checks


def main() -> int:
    """Save exact work estimates first, then run only the small restricted pilot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "results/pilots/greedy")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["dataset"] != "email-Eu-core":
        raise ValueError("This smoke pilot supports only email-Eu-core; no Facebook/Wiki-Vote benchmark")
    if config["candidate_pool_policy"] != "top-unweighted-out-degree":
        raise ValueError("Unknown explicit candidate-pool policy")
    pool_size, simulations, k = (config[key] for key in ("candidate_pool_size", "number_of_simulations", "protector_budget"))
    if (type(pool_size) is not int or not 1 <= pool_size <= 20
            or type(simulations) is not int or not 1 <= simulations <= 50
            or type(k) is not int or not 1 <= k <= min(3, pool_size)):
        raise ValueError("Smoke pilot requires pool<=20, 1<=S<=50, and 1<=k<=min(3,pool)")
    output = args.output_dir
    protected = (PROJECT_ROOT / "data").resolve()
    for path in (output, *(output / name for name in OUTPUT_NAMES)):
        resolved = path.resolve()
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("Pilot output must not overwrite raw/processed data")
    started = perf_counter()
    before = _data_hashes()
    small_checks = _check_small_graphs()
    graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
    rumor = config["rumor_seeds"]
    full_cost = estimate_greedy_cost(len(graph) - len(set(rumor)), k, simulations)
    # This exact estimate is printed/saved before any real-data Greedy call.
    print(f"Full Greedy email cost: {full_cost.evaluation_count} evaluations / "
          f"{full_cost.cic_simulation_count} CIC simulations; NOT EXECUTED.", flush=True)
    pool_started = perf_counter()
    pool = select_degree(graph, rumor, pool_size)
    pool_runtime = perf_counter() - pool_started
    restricted_cost = estimate_greedy_cost(len(pool), k, simulations)
    print(f"Candidate-Restricted Greedy cost per search: {restricted_cost.evaluation_count} evaluations / "
          f"{restricted_cost.cic_simulation_count} CIC simulations.", flush=True)
    output.mkdir(parents=True, exist_ok=True)
    preflight = {
        "full_greedy_email": asdict(full_cost), "full_greedy_email_executed": False,
        "candidate_restricted_greedy_email": asdict(restricted_cost),
        "candidate_pool_policy": config["candidate_pool_policy"], "candidate_nodes": sorted(pool),
        "runtime_prediction_seconds": None,
        "note": "Exact evaluation/simulation counts are not measured or predicted wall-clock time.",
    }
    (output / "preflight.json").write_text(json.dumps(preflight, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output / "config.json").write_text(json.dumps(config, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    parameters = {
        "candidate_nodes": pool, "base_random_seed": config["base_random_seed"],
        "tie_breaking": config["tie_breaking"],
    }
    result = select_candidate_restricted_greedy(
        graph, rumor, k, config["propagation_probability"], simulations, **parameters,
    )
    replay = select_candidate_restricted_greedy(
        graph, rumor, k, config["propagation_probability"], simulations, **parameters,
    )
    if result != replay:
        raise RuntimeError("Restricted Greedy replay changed selection/history/trial scores")
    if result.evaluation_count != restricted_cost.evaluation_count:
        raise RuntimeError("Measured evaluation count differs from the preflight estimate")
    with (output / "steps.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("algorithm", "step_index", "selected_node", "protector_nodes",
                                                   "mean_rumor_count", "std_rumor_count", "evaluation_count"), lineterminator="\n")
        writer.writeheader()
        for step in result.steps:
            writer.writerow({"algorithm": result.algorithm, "step_index": step.step_index,
                             "selected_node": step.selected_node, "protector_nodes": json.dumps(sorted(step.protector_nodes)),
                             "mean_rumor_count": step.mean_rumor_count, "std_rumor_count": step.std_rumor_count,
                             "evaluation_count": step.evaluation_count})
    with (output / "trials.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("algorithm", "step_index", "candidate_node", "trial_protector_nodes",
                                                   "mean_rumor_count", "std_rumor_count", "mean_protector_count",
                                                   "mean_inactive_count", "evaluation_runtime_seconds"), lineterminator="\n")
        writer.writeheader()
        previous = set()
        for step in result.steps:
            for trial in step.candidate_evaluations:
                writer.writerow({"algorithm": result.algorithm, "step_index": step.step_index,
                                 "trial_protector_nodes": json.dumps(sorted(previous | {trial.candidate_node})), **asdict(trial)})
            previous.add(step.selected_node)
    after = _data_hashes()
    if before != after:
        raise RuntimeError("Raw/processed data changed during the Greedy pilot")
    report = {
        "purpose": "greedy_implementation_smoke_pilot_only", "official_thesis_result": False,
        "config": config, "preflight": preflight, "small_full_greedy_checks": small_checks,
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "environment": {"python": platform.python_version(), "networkx": nx.__version__,
                        "platform": platform.platform(), "machine": platform.machine()},
        "candidate_pool_selection_runtime_seconds": pool_runtime,
        "result": _result_dict(result),
        "replay_evaluation_count": replay.evaluation_count, "replay_runtime_seconds": replay.runtime_seconds,
        "repeatability_verified_excluding_runtime": True,
        "real_dataset_searches": {"full_greedy": 0, "candidate_restricted_greedy": 2},
        "total_real_dataset_evaluations_including_replay": result.evaluation_count + replay.evaluation_count,
        "total_real_dataset_cic_simulations_including_replay": result.cic_simulation_count + replay.cic_simulation_count,
        "total_pilot_evaluations_including_toys_and_replay": result.evaluation_count + replay.evaluation_count
            + sum(case["result"]["evaluation_count"] for case in small_checks),
        "total_pilot_cic_simulations_including_toys_and_replay": result.cic_simulation_count + replay.cic_simulation_count
            + sum(case["result"]["cic_simulation_count"] for case in small_checks),
        "data_sha256_before": before, "data_sha256_after": after, "source_data_unchanged": True,
        "pilot_wall_runtime_seconds_excluding_report_write": perf_counter() - started,
        "limitations": [
            "Only tiny graphs use Full Greedy. Email uses a named, degree-restricted pool; no graph is pruned.",
            "S=20 is an execution smoke budget, below the 4A precision recommendations.",
            "Trial scores are used for optimization, not fresh held-out quality estimates.",
            "Greedy is locally optimal per sampled next-step objective, not globally optimal over k-subsets.",
            "No CELF/lazy pruning or submodularity assumption is used.",
            "All trials share the evaluator's seed schedule, not guaranteed common edge-level outcomes.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"PILOT ONLY: {result.algorithm}, order={result.selection_order}, "
          f"optimization mean={result.final_mean_rumor_count}, evaluations={result.evaluation_count}, "
          f"runtime={result.runtime_seconds:.6f}s (MC portion={result.evaluation_runtime_seconds:.6f}s).", flush=True)
    print(f"Email calls including replay: {report['total_real_dataset_evaluations_including_replay']}; "
          f"CIC simulations: {report['total_real_dataset_cic_simulations_including_replay']}. Saved to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
