"""Milestone 4A pilot: fixed baselines and independent Monte Carlo batches."""

import argparse
from collections import defaultdict
import csv
from dataclasses import asdict
import json
from math import ceil, fsum, isfinite, sqrt
from pathlib import Path
import platform
from random import Random
from statistics import fmean, stdev
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
import os

import networkx as nx
import scipy

from src.algorithms import select_degree, select_pagerank, select_random
from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.diffusion import TieBreakingRule
from src.evaluation import evaluate_cic


DEFAULT_CONFIG = PROJECT_ROOT / "experiments/configs/mc_stability_email.json"
OUTPUT_NAMES = (
    "config.json", "selections.csv", "batches.csv", "raw_results.csv",
    "summary.csv", "rankings.csv", "report.json", "analysis.md", "stability.png",
)


def validate_config(config: dict[str, Any]) -> None:
    """Validate the batch design before running selections or simulations."""
    for key in ("protector_budget", "selection_random_seed", "first_batch_base_seed",
                "execution_order_seed", "batch_seed_stride", "number_of_batches"):
        value = config[key]
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if config["number_of_batches"] < 2:
        raise ValueError("At least two independent batches are required")
    counts = config["simulation_counts"]
    if not counts or any(type(s) is not int or s < 2 for s in counts) or len(set(counts)) != len(counts):
        raise ValueError("simulation_counts must be distinct integers >= 2")
    if config["batch_seed_stride"] < max(counts):
        raise ValueError("batch_seed_stride must prevent overlapping seed blocks")
    p = config["propagation_probability"]
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
        raise ValueError("propagation_probability must be in [0, 1]")
    TieBreakingRule(config["tie_breaking"])
    for key in ("opt_standard_error_fraction_of_nodes", "eval_standard_error_fraction_of_nodes"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if config["eval_standard_error_fraction_of_nodes"] > config["opt_standard_error_fraction_of_nodes"]:
        raise ValueError("Evaluation SE target must be at least as strict as optimization target")
    if not isinstance(config["rumor_seeds"], list) or not config["rumor_seeds"]:
        raise ValueError("A nonempty fixed rumor_seeds list is required")


def summarize_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Separate spread variability, batch-mean variability and pooled SE."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["method"], row["simulations"]].append(row)
    summaries = []
    for (method, s), batches in sorted(groups.items()):
        means = [row["mean_rumor_count"] for row in batches]
        pooled_mean = fmean(means)
        total = s * len(batches)
        # Within-batch sum of squares uses the unchanged evaluator's ddof=0 std.
        ss = fsum(s * row["std_rumor_population"] ** 2 + s * (row["mean_rumor_count"] - pooled_mean) ** 2
                  for row in batches)
        pooled_std = sqrt(ss / (total - 1))
        runtimes = [row["evaluation_runtime_seconds"] for row in batches]
        summaries.append({
            "method": method, "simulations": s, "batches": len(batches),
            "mean_rumor_count": pooled_mean,
            "batch_mean_std": stdev(means) if len(means) > 1 else 0.0,
            "min_batch_mean": min(means), "max_batch_mean": max(means),
            "mean_std_rumor_population": fmean(row["std_rumor_population"] for row in batches),
            "mean_standard_error": fmean(row["standard_error"] for row in batches),
            "max_standard_error": max(row["standard_error"] for row in batches),
            "pooled_rumor_std_sample": pooled_std,
            "pooled_standard_error": pooled_std / sqrt(total),
            "mean_protector_count": fmean(row["mean_protector_count"] for row in batches),
            "mean_inactive_count": fmean(row["mean_inactive_count"] for row in batches),
            "mean_evaluation_runtime_seconds": fmean(runtimes),
            "std_evaluation_runtime_seconds": stdev(runtimes) if len(runtimes) > 1 else 0.0,
        })
    return summaries


def recommend_simulations(summaries: list[dict[str, Any]], nodes: int,
                          config: dict[str, Any]) -> dict[str, Any]:
    """Apply declared SE targets to single-batch costs, with explicit fallback."""
    counts = sorted({row["simulations"] for row in summaries})
    worst = {s: max(row["max_standard_error"] for row in summaries if row["simulations"] == s) for s in counts}
    largest_std = max(row["pooled_rumor_std_sample"] for row in summaries if row["simulations"] == counts[-1])
    recommendations = {}
    for name, key in (("S_opt", "opt_standard_error_fraction_of_nodes"),
                      ("S_eval", "eval_standard_error_fraction_of_nodes")):
        target = config[key] * nodes
        eligible = [s for s in counts if worst[s] <= target]
        chosen = min(eligible) if eligible else max(counts)
        recommendations[name] = {
            "simulations": chosen, "target_standard_error_nodes": target,
            "target_met": bool(eligible), "worst_observed_standard_error": worst[chosen],
            "estimated_simulations_for_target": max(2, ceil((largest_std / target) ** 2)),
            "worst_mean_evaluation_runtime_seconds": max(
                row["mean_evaluation_runtime_seconds"] for row in summaries if row["simulations"] == chosen),
            "status": "pilot_candidate" if eligible else "largest_tested_budget_target_not_met",
        }
    return recommendations


def summarize_rankings(rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report ranking agreement for these fixed P sets, excluding no intervention."""
    result = []
    for s in sorted({row["simulations"] for row in rows}):
        consensus = [row["method"] for row in sorted(
            (row for row in summaries if row["simulations"] == s and row["method"] != "none"),
            key=lambda row: (row["mean_rumor_count"], row["method"]))]
        rankings = []
        for batch in sorted({row["batch"] for row in rows}):
            rankings.append([row["method"] for row in sorted(
                (row for row in rows if row["simulations"] == s and row["batch"] == batch and row["method"] != "none"),
                key=lambda row: (row["mean_rumor_count"], row["method"]))])
        result.append({"simulations": s, "consensus_ranking": consensus,
                       "agreement_fraction": sum(rank == consensus for rank in rankings) / len(rankings),
                       "batch_rankings": rankings})
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def _plot(summaries: list[dict[str, Any]], output: Path, config: dict[str, Any]) -> None:
    """Export a standalone pilot figure after all timing measurements finish."""
    with TemporaryDirectory(prefix="stability-mpl-") as temporary:
        previous = os.environ.get("MPLCONFIGDIR")
        os.environ["MPLCONFIGDIR"] = temporary
        try:
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib import pyplot as plt
            fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
            for method in ("none", "random", "degree", "pagerank"):
                group = sorted((row for row in summaries if row["method"] == method), key=lambda row: row["simulations"])
                x = [row["simulations"] for row in group]
                axes[0, 0].errorbar(x, [row["mean_rumor_count"] for row in group],
                                   yerr=[row["batch_mean_std"] for row in group], marker="o", label=method, capsize=3)
                for ax, key in ((axes[0, 1], "mean_std_rumor_population"),
                                (axes[1, 0], "max_standard_error"),
                                (axes[1, 1], "mean_evaluation_runtime_seconds")):
                    ax.plot(x, [row[key] for row in group], marker="o", label=method)
            titles = ("Rumor mean +/- batch-mean SD", "Mean population SD of rumor counts",
                      "Maximum single-batch standard error", "Mean MC evaluation runtime (seconds)")
            for ax, title in zip(axes.flat, titles):
                ax.set_title(title)
                ax.set_xlabel("Simulations per evaluation (S)")
                ax.grid(alpha=0.25)
                ax.legend()
            fig.suptitle(f"PILOT ONLY - {config['dataset']}, fixed R/P, p={config['propagation_probability']}, "
                         f"{config['number_of_batches']} independent batches")
            fig.savefig(output, dpi=160)
            plt.close(fig)
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = previous


def run_pilot(graph: nx.Graph, config: dict[str, Any], output_directory: Path,
              *, plot: bool = True, progress: bool = True) -> dict[str, Any]:
    """Select P once, evaluate every batch/S using evaluate_cic, export evidence."""
    validate_config(config)
    output = Path(output_directory)
    protected = (PROJECT_ROOT / "data").resolve()
    for path in (output, *(output / name for name in OUTPUT_NAMES)):
        resolved = path.resolve()
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("Pilot output must not write into raw/processed data")
    before_hashes = {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p)
                     for p in sorted((PROJECT_ROOT / "data").rglob("*")) if p.is_file()}
    rumor = config["rumor_seeds"]
    k = config["protector_budget"]
    selections = [{"method": "none", "protector_seeds": [], "selection_runtime_seconds": 0.0}]
    for method, selector, parameters in (
        ("random", select_random, {"random_seed": config["selection_random_seed"]}),
        ("degree", select_degree, {}), ("pagerank", select_pagerank, config["pagerank"]),
    ):
        started = perf_counter()
        protector = selector(graph, rumor, k, **parameters)
        elapsed = perf_counter() - started
        selections.append({"method": method, "protector_seeds": sorted(protector), "selection_runtime_seconds": elapsed})
    methods = {row["method"]: row for row in selections}
    tasks = [(batch, s, method) for batch in range(config["number_of_batches"])
             for s in sorted(config["simulation_counts"]) for method in methods]
    Random(config["execution_order_seed"]).shuffle(tasks)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with (output / "raw_results.csv").open("w", encoding="utf-8", newline="") as stream:
        raw_writer = csv.DictWriter(stream, fieldnames=("method", "simulations", "batch", "simulation_index",
                                                       "random_seed", "rumor_count", "protector_count", "inactive_count", "steps"),
                                    lineterminator="\n")
        raw_writer.writeheader()
        for position, (batch, s, method) in enumerate(tasks, 1):
            selection = methods[method]
            base = config["first_batch_base_seed"] + batch * config["batch_seed_stride"]
            estimate = evaluate_cic(
                graph, rumor, selection["protector_seeds"], config["propagation_probability"], s,
                base_random_seed=base, tie_breaking=config["tie_breaking"],
            )
            rows.append({
                "method": method, "simulations": s, "batch": batch, "base_random_seed": base,
                "rumor_seeds": rumor, "protector_seeds": selection["protector_seeds"],
                "protector_budget": len(selection["protector_seeds"]),
                "propagation_probability": config["propagation_probability"], "tie_breaking": config["tie_breaking"],
                "mean_rumor_count": estimate.mean_rumor_count,
                "std_rumor_population": estimate.std_rumor_count,
                "std_rumor_sample": estimate.std_rumor_count * sqrt(s / (s - 1)),
                "standard_error": estimate.std_rumor_count / sqrt(s - 1),
                "mean_protector_count": estimate.mean_protector_count,
                "mean_inactive_count": estimate.mean_inactive_count,
                "min_rumor_count": estimate.min_rumor_count, "max_rumor_count": estimate.max_rumor_count,
                "evaluation_runtime_seconds": estimate.runtime_seconds,
            })
            for run in estimate.raw_results:
                raw_writer.writerow({"method": method, "simulations": s, "batch": batch, **asdict(run)})
            if progress and (position % 10 == 0 or position == len(tasks)):
                print(f"Pilot evaluations: {position}/{len(tasks)}", flush=True)
    rows.sort(key=lambda row: (row["method"], row["simulations"], row["batch"]))
    summaries = summarize_batches(rows)
    recommendations = recommend_simulations(summaries, len(graph), config)
    rankings = summarize_rankings(rows, summaries)
    for name, values in (("selections.csv", selections), ("batches.csv", rows),
                         ("summary.csv", summaries), ("rankings.csv", rankings)):
        _write_csv(output / name, values)
    (output / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if plot:
        _plot(summaries, output / "stability.png", config)
    after_hashes = {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p)
                    for p in sorted((PROJECT_ROOT / "data").rglob("*")) if p.is_file()}
    if before_hashes != after_hashes:
        raise RuntimeError("Dataset files changed during the stability pilot")
    report = {
        "purpose": "baseline_and_monte_carlo_stability_pilot_only", "official_thesis_result": False,
        "config": config, "selections": selections, "batches": rows, "summary": summaries,
        "rankings": rankings, "recommendations": recommendations,
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "environment": {"python": platform.python_version(), "networkx": nx.__version__, "scipy": scipy.__version__,
                        "platform": platform.platform(), "machine": platform.machine()},
        "seed_design": {
            "formula": "seed(batch,i) = first_batch_base_seed + batch*batch_seed_stride + i",
            "batch_blocks_disjoint": True, "nested_prefixes_across_S": True,
            "shared_schedule_across_methods": True,
            "edge_level_common_random_numbers_guaranteed": False,
            "execution_order_seed": config["execution_order_seed"],
        },
        "total_evaluations": len(rows), "total_cic_simulations": sum(row["simulations"] for row in rows),
        "total_selection_runtime_seconds": fsum(row["selection_runtime_seconds"] for row in selections),
        "total_evaluation_runtime_seconds": fsum(row["evaluation_runtime_seconds"] for row in rows),
        "data_sha256_before": before_hashes, "data_sha256_after": after_hashes, "source_data_unchanged": True,
        "artifact_sha256": {name: sha256_file(output / name) for name in OUTPUT_NAMES if (output / name).is_file()
                            and name not in ("report.json", "analysis.md")},
        "limitations": [
            "One fixed rumor set, one fixed P per baseline, one dataset/p/k; no official algorithm comparison.",
            "Population count SD need not shrink with S; single-batch SE is sample SD/sqrt(S).",
            "S recommendations use worst single-batch SE across methods, not pooled SE over all batches.",
            "S values share prefixes inside a batch; batches use disjoint seed blocks.",
            "Selection costs occur once per fixed P; MC costs are measured for every S/batch separately.",
            "SE thresholds are declared pilot engineering targets, not confidence guarantees.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Milestone 4A pilot only", "", "Not official thesis results.", "",
             "| S | Worst single-batch SE | Worst batch-mean SD | Worst mean MC runtime (s) |",
             "|---:|---:|---:|---:|"]
    for s in sorted(config["simulation_counts"]):
        group = [row for row in summaries if row["simulations"] == s]
        lines.append(f"| {s} | {max(row['max_standard_error'] for row in group):.4f} | "
                     f"{max(row['batch_mean_std'] for row in group):.4f} | "
                     f"{max(row['mean_evaluation_runtime_seconds'] for row in group):.6f} |")
    lines += ["", "Recommendations (conditional on this pilot):", "", json.dumps(recommendations, indent=2), "",
              "Population SD of counts differs from SE and between-batch SD of means. See report.json for all configurations,",
              "selection times, raw replay seeds, pooled statistics, ranking agreement and limitations.", ""]
    (output / "analysis.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    """Run the saved email pilot configuration and print measured recommendations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "results/pilots/mc_stability")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config)
    graph = load_processed_graph(PROJECT_ROOT / "data/processed" / config["dataset"])
    report = run_pilot(graph, config, args.output_dir)
    print(json.dumps(report["recommendations"], indent=2), flush=True)
    print(f"PILOT ONLY. Saved {report['total_evaluations']} evaluations to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
