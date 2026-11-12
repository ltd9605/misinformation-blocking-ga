"""Derive calibration diagnostics from measured artifacts; performs no CIC calls."""

import argparse
from collections import defaultdict
from itertools import combinations
import json
from math import sqrt
from pathlib import Path
from statistics import mean

from experiments.pilot_protocol_validation import write_csv, write_json
from src.experiments.calibration import observation_summary


def order_agreement(first: dict[str, float], second: dict[str, float]) -> dict:
    """Keep ties explicit instead of mistaking label tie-breaks for certainty."""
    methods = sorted(first.keys() & second.keys())
    flips = ties_changed = agreement = 0
    for a, b in combinations(methods, 2):
        one = (first[a] > first[b]) - (first[a] < first[b])
        two = (second[a] > second[b]) - (second[a] < second[b])
        flips += one * two < 0
        ties_changed += (one == 0) != (two == 0)
        agreement += one == two
    count = len(methods)*(len(methods)-1)//2
    return {"method_count": len(methods), "pair_count": count, "strict_order_flips": flips,
            "tie_status_changes": ties_changed, "order_agreement_fraction": agreement/count if count else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/pilot_2_calibration"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    execution = json.loads((root/"optimization_execution.json").read_text())
    preflight = json.loads((root/"optimization_preflight.json").read_text())
    plans = {v["case_id"]: v for v in preflight}
    statuses, gap_rows, runtime_rows, optimization_means = [], [], [], {}
    for case in execution:
        context = {k: case[k] for k in ("case_id", "phase", "dataset", "S_opt", "repeat")}
        if case["status"] != "completed":
            for plan in plans[case["case_id"]]["preflight"]:
                statuses.append({**context, "algorithm": plan["algorithm"], "status": "skipped",
                                 "reason": plan["reason"] if plan["status"] == "skipped" else case["reason"],
                                 "actual_cic_simulations": 0})
            continue
        directory = Path(case["run_directory"])
        summary = json.loads((directory/"summary.json").read_text())
        runtime_rows.append({**context, **summary["timings"], "subprocess_wall_seconds": case["subprocess_wall_seconds"],
                             "optimization_evaluator_calls": summary["total_optimization_evaluations"],
                             "final_evaluator_calls": summary["total_final_evaluations"], "cic_simulations": summary["total_cic_simulations"],
                             "projected_before_execution_seconds": case["projected_runtime_seconds"]})
        for status in summary["method_statuses"]:
            statuses.append({**context, **status, "actual_cic_simulations": status["cic_simulations"]})
        optimization_means[case["case_id"]] = {r["algorithm"]: r["rumor_mean"] for r in summary["results"]}
        for result in summary["results"]:
            score = result["optimization_best_estimated_fitness"]
            if score is not None:
                gap_rows.append({**context, "algorithm": result["algorithm"], "optimization_fitness": score,
                                 "final_mean": result["rumor_mean"], "final_SE": result["rumor_standard_error"],
                                 "final_minus_optimization": result["rumor_mean"]-score,
                                 "protector_seeds": result["protector_seeds"]})
    write_csv(root/"method_status.csv", statuses)
    write_json(root/"method_status.json", statuses)
    write_csv(root/"runtime_by_comparison.csv", runtime_rows)
    write_csv(root/"fitness_gaps.csv", gap_rows)

    accuracy = json.loads((root/"accuracy_statistics.json").read_text())
    grouped = defaultdict(list)
    accuracy_means = defaultdict(dict)
    for row in accuracy:
        grouped[(row["dataset"], row["algorithm"], row["S_eval"])].append(row)
        accuracy_means[(row["dataset"], row["batch"], row["S_eval"])][row["algorithm"]] = row["rumor_mean"]
    stability, independent_gaps = [], []
    for (dataset, method, s), rows in grouped.items():
        row = {"dataset": dataset, "algorithm": method, "S_eval": s, "independent_batches": len(rows),
               "mean_of_batch_means": mean(v["rumor_mean"] for v in rows),
               "max_SE": max(v["rumor_SE"] for v in rows),
               "max_CI_halfwidth_nodes": max(v["ci95_half_width"] for v in rows),
               "max_relative_CI_halfwidth": max(v["ci95_half_width"]/v["rumor_mean"] for v in rows if v["rumor_mean"] > 0),
               "runtime_MC_both_batches_seconds": sum(v["runtime_prefix_MC_seconds"] for v in rows)}
        if len(rows) == 2:
            first, second = sorted(rows, key=lambda v: v["batch"])
            row.update(between_batch_mean_difference=first["rumor_mean"]-second["rumor_mean"],
                       between_batch_standardized_difference=abs(first["rumor_mean"]-second["rumor_mean"])/sqrt(first["rumor_SE"]**2+second["rumor_SE"]**2)
                         if first["rumor_SE"] or second["rumor_SE"] else None,
                       batch_CIs_overlap=first["ci95_low"] <= second["ci95_high"] and second["ci95_low"] <= first["ci95_high"])
        stability.append(row)
        for v in rows:
            if v["optimization_fitness"] is not None:
                independent_gaps.append({"dataset": dataset, "algorithm": method, "S_eval": s, "batch": v["batch"],
                                         "optimization_fitness": v["optimization_fitness"], "independent_mean": v["rumor_mean"],
                                         "gap": v["final_minus_optimization"],
                                         "heldout_CI_minus_observed_training_low": v["ci95_low"]-v["optimization_fitness"],
                                         "heldout_CI_minus_observed_training_high": v["ci95_high"]-v["optimization_fitness"]})
    write_csv(root/"accuracy_stability.csv", stability)
    write_json(root/"accuracy_stability.json", stability)
    write_csv(root/"independent_accuracy_fitness_gaps.csv", independent_gaps)

    agreements = []
    def compare(context, first, second):
        for scope in ("all_methods", "protector_methods_only"):
            a, b = dict(first), dict(second)
            if scope == "protector_methods_only":
                a.pop("no_intervention", None)
                b.pop("no_intervention", None)
            agreements.append({**context, "scope": scope, **order_agreement(a, b)})
    for a, b in combinations(accuracy_means, 2):
        if a[0] != b[0] or (a[1] != b[1] and a[2] != b[2]):
            continue
        compare({"phase": "accuracy", "dataset": a[0], "comparison_type": "nested_S_eval_prefix" if a[1] == b[1] else "independent_accuracy_batches",
                 "first_batch": a[1], "second_batch": b[1], "first_S_eval": a[2], "second_S_eval": b[2]}, accuracy_means[a], accuracy_means[b])
    active = [c for c in execution if c["phase"] == "optimization" and c["status"] == "completed"]
    for a, b in combinations(active, 2):
        if a["dataset"] != b["dataset"] or (a["repeat"] != b["repeat"] and a["S_opt"] != b["S_opt"]):
            continue
        compare({"phase": "optimization", "dataset": a["dataset"], "comparison_type": "paired_S_opt" if a["repeat"] == b["repeat"] else "independent_optimization_repeats",
                 "first_repeat": a["repeat"], "second_repeat": b["repeat"], "first_S_opt": a["S_opt"], "second_S_opt": b["S_opt"]},
                optimization_means[a["case_id"]], optimization_means[b["case_id"]])
    write_csv(root/"ranking_stability.csv", agreements)
    write_json(root/"ranking_stability.json", agreements)
    # Pooled fixed-P accuracy is additional context, not the SE of one S_eval run.
    pooled = []
    reachable = json.loads((root/"reachable_summary.json").read_text())
    representatives = json.loads((root/"representatives.json").read_text())
    for dataset in json.loads((root/"config.json").read_text())["datasets"]:
        for method in ("no_intervention", "random", "degree", "pagerank", "candidate_restricted_greedy", "genetic_algorithm"):
            paths = sorted((root/"accuracy").glob(f"{dataset}_b*_{method}.json"))
            records = [r for p in paths for r in json.loads(p.read_text())["raw_results"]]
            if records:
                scenario = representatives[dataset]
                n = reachable[dataset]["node_count"]
                pooled.append({"dataset": dataset, "algorithm": method, "independent_batches": len(paths),
                               **observation_summary([v["rumor_count"] for v in records], n, scenario["reachable_count"])})
    write_csv(root/"pooled_fixed_P_accuracy.csv", pooled)
    summary = {"measured_primary_budget": json.loads((root/"budget.json").read_text()),
               "completed_comparisons": len(runtime_rows), "completed_optimization_comparisons": len(active),
               "skipped_optimization_comparisons": sum(c["phase"] == "optimization" and c["status"] == "skipped" for c in execution),
               "completed_method_rows": sum(s["status"] == "completed" for s in statuses),
               "skipped_method_rows": sum(s["status"] == "skipped" for s in statuses),
               "accuracy_rows": len(accuracy), "accuracy_stability": stability,
               "measured_vs_projected": "runtime_by_comparison contains both measured and prior projected values; proposed main settings are not executions",
               "inference_scope": "pointwise exploratory 95% t intervals; paired differences by seed, no multiplicity correction or algorithm-winner claim"}
    write_json(root/"calibration_analysis.json", summary)
    make_figures(root, accuracy)
    return 0


def make_figures(root: Path, accuracy: list[dict]) -> None:
    """Standalone scientific plots of topology mass and fixed-P uncertainty."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    summaries = json.loads((root/"reachable_summary.json").read_text())
    fig, axes = plt.subplots(1, len(summaries), figsize=(13, 3.7), squeeze=False)
    for ax, (name, summary) in zip(axes[0], summaries.items()):
        values = summary["histogram"]
        ax.bar([str(v["reachable_count"]) for v in values], [v["source_node_count"] for v in values])
        ax.set_yscale("log")
        ax.set_title(name)
        ax.set_xlabel("Exact reachable set size (including source)")
        ax.set_ylabel("Source nodes (log scale)")
        ax.tick_params(axis="x", rotation=70)
    fig.tight_layout()
    fig.savefig(root/"reachable_distribution.png", dpi=160)
    plt.close(fig)
    names = list(summaries)
    fig, axes = plt.subplots(1, len(names), figsize=(13, 3.7), squeeze=False)
    for ax, name in zip(axes[0], names):
        for batch, marker in ((0, "o"), (1, "s")):
            rows = sorted([v for v in accuracy if v["dataset"] == name and v["algorithm"] == "no_intervention" and v["batch"] == batch], key=lambda v: v["S_eval"])
            ax.errorbar([v["S_eval"] for v in rows], [v["rumor_mean"] for v in rows], yerr=[v["ci95_half_width"] for v in rows], marker=marker, capsize=4, label=f"Independent batch {batch}")
        ax.set_title(name + " (No Intervention)")
        ax.set_xlabel("S_eval (nested prefixes within each batch)")
        ax.set_ylabel("Mean rumor count, pointwise 95% t CI")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(root/"mc_accuracy.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
