"""Export observed V2 runs and descriptive OFAT uncertainty; never select a winner.

Independent GA runs are the replication unit. Paired contrasts use the same
final CIC seed schedule in a repetition, without assuming edge-wise coupling.
Eight approximate Bonferroni t intervals supplement pointwise intervals.
"""

import argparse
from collections import Counter
import json
from math import sqrt
import os
from pathlib import Path
from statistics import mean, stdev
from tempfile import gettempdir
from time import perf_counter

os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir())/"misinformation-screen-v2-matplotlib"))

from scipy.stats import t

from experiments.pilot_protocol_validation import write_csv, write_json
from experiments.reduced_screen_v2 import atomic_json, fingerprint
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.calibration import jaccard, observation_summary, paired_differences
from src.experiments.sensitivity import FACTORS, variance_components


def contrast_summary(differences: list[float], conditional_ses: list[float], family_size: int = 8) -> dict:
    """GA-run uncertainty of a predeclared paired contrast, not MC pseudoreplication."""
    if len(differences) < 2 or family_size < 1:
        raise ValueError("At least two independent differences and a positive family required")
    n = len(differences)
    average, sd = mean(differences), stdev(differences)
    se = sd/sqrt(n)
    point = float(t.ppf(.975, n-1))*se
    simultaneous = float(t.ppf(1-.05/(2*family_size), n-1))*se
    low, high = average-simultaneous, average+simultaneous
    conclusion = "insufficient_evidence_of_difference"
    if sd > 0 and high < 0:
        conclusion = "lower_final_rumor_on_this_scenario_only_approximate_family_CI"
    elif sd > 0 and low > 0:
        conclusion = "higher_final_rumor_on_this_scenario_only_approximate_family_CI"
    return {"difference_direction": "alternative_minus_reference_lower_is_better", "independent_GA_pairs": n,
            "mean_difference": average, "std_across_GA_pairs": sd, "SE_across_GA_pairs": se,
            "pointwise_CI95_low": average-point, "pointwise_CI95_high": average+point,
            "family_size": family_size, "Bonferroni_family_CI95_low": low, "Bonferroni_family_CI95_high": high,
            "conclusion": conclusion, "zero_empirical_variance_warning": sd == 0,
            "variance_components_of_difference": variance_components(differences, conditional_ses)}


def row_summary(result: dict, control: dict | None = None) -> dict:
    """One GA outcome with a conditional CI for its fixed final protector set."""
    r, core, f = result["row"], result["core_GA_result"], result["final"]
    return {**r, "status": "completed", "reason": None, "protector_seeds": result["protector_seeds"],
            "training_fitness": result["training_fitness"], "independent_mean": f["rumor_mean"],
            "independent_std_population": f["rumor_std_population"], "independent_std_sample": f["rumor_std_sample"],
            "independent_MC_SE": f["rumor_SE"], "independent_MC_CI95_low": f["ci95_low"],
            "independent_MC_CI95_high": f["ci95_high"], "final_simulations": f["S"],
            "independent_minus_training": f["rumor_mean"]-result["training_fitness"],
            "control_mean": control["rumor_mean"] if control else None,
            "spread_reduction_fraction": 1-f["rumor_mean"]/control["rumor_mean"] if control and control["rumor_mean"] else None,
            "selection_runtime_seconds": result["selection_runtime_seconds"],
            "fitness_MC_runtime_seconds": result["fitness_evaluator_runtime_seconds"],
            "selection_non_MC_seconds": result["selection_runtime_seconds"]-result["fitness_evaluator_runtime_seconds"],
            "final_evaluation_runtime_seconds": result["final_evaluation_runtime_seconds"],
            "graph_loading_seconds": result["graph_loading_seconds"], "worker_runtime_seconds": result["worker_runtime_seconds"],
            "generations_run": core["generations_run"], "optimization_evaluator_calls": core["evaluation_count"],
            "final_evaluator_calls": r["final_batches"], "evaluator_calls": result["evaluator_calls"],
            "optimization_CIC_simulations": core["cic_simulation_count"], "CIC_simulations": result["CIC_simulations"],
            "fitness_request_count": core["fitness_request_count"], "cache_hits": core["cache_hit_count"],
            "elite_fitness_reuse_count": core["elite_fitness_reuse_count"], "graph_unchanged": result["graph_unchanged"]}


def audit_observed(plan: dict, results: dict, controls: dict) -> dict:
    """Recompute invariants/counters/statistics from completed experimental records."""
    expected = {r["run_id"]: r for r in plan["matrix"]}
    generations, individuals, final_observations, elite_checks = 0, 0, 0, 0
    node_count = round(plan["scenario"]["reachable_count"]/plan["scenario"]["reachable_fraction_of_graph"])
    def require(condition, label):
        if not condition:
            raise ValueError(f"Observed artifact audit failed: {label}")
    for run_id, result in results.items():
        row, core = result["row"], result["core_GA_result"]
        require(row == expected[run_id], "frozen row")
        require(len(core["history"]) == row["max_generations"]+1, "generation count")
        require(core["seeds"]["fitness_base_random_seed"] == row["optimization_base_random_seed"], "fitness seed")
        require(core["seeds"]["operators_seed"] == row["GA_operators_seed"], "operator seed")
        require(len(core["fitness_evaluations"]) == core["evaluation_count"], "fitness calls")
        require(core["cic_simulation_count"] == core["evaluation_count"]*row["S_opt"], "fitness CIC")
        require(len({tuple(e["protector_nodes"]) for e in core["fitness_evaluations"]}) == core["evaluation_count"], "local cache uniqueness")
        eligible, rumor = set(core["eligible_nodes"]), set(row["rumor_seeds"])
        previous = None
        for g, history in enumerate(core["history"]):
            generations += 1
            require(history["generation"] == g, "generation ordinal")
            require(len(history["population"]) == row["population_size"], "population size")
            require(len(history["fitness_values"]) == row["population_size"], "fitness vector")
            for P in history["population"]:
                individuals += 1
                require(len(P) == len(set(P)) == row["k"] and set(P) <= eligible and not set(P)&rumor, "individual feasibility")
            if previous:
                ranked = sorted(zip(previous["fitness_values"], previous["population"]), key=lambda pair: (pair[0], pair[1]))
                carried = Counter((f, tuple(P)) for f, P in zip(history["fitness_values"], history["population"]))
                required = Counter((f, tuple(P)) for f, P in ranked[:row["elitism_count"]])
                require(all(carried[key] >= count for key, count in required.items()), "elite preservation")
                elite_checks += row["elitism_count"]
            previous = history
        pooled = []
        require(len(result["final_batches"]) == row["final_batches"], "final batches")
        for b, batch in enumerate(result["final_batches"]):
            require(batch["base_seed"] == row["final_batch_seeds"][b] and len(batch["rumor_counts"]) == row["S_eval"], "final seed/count")
            require(batch["statistics"] == observation_summary(batch["rumor_counts"], node_count), "batch statistics")
            pooled.extend(batch["rumor_counts"])
        require(result["final"] == observation_summary(pooled, node_count), "pooled statistics")
        require(result["CIC_simulations"] == core["cic_simulation_count"]+len(pooled), "run CIC")
        require(result["evaluator_calls"] == core["evaluation_count"]+row["final_batches"], "run evaluator calls")
        final_observations += len(pooled)
    for (repeat, b), control in controls.items():
        row = next(r for r in plan["matrix"] if r["profile_id"] == "reference" and r["repetition_index"] == repeat)
        require(control["base_seed"] == row["final_batch_seeds"][b], "control seed")
        require(len(control["rumor_counts"]) == row["S_eval"], "control S")
        require(control["final"] == observation_summary(control["rumor_counts"], node_count), "control statistics")
        final_observations += len(control["rumor_counts"])
    return {"passed": True, "completed_GA_runs_audited": len(results), "convergence_rows": generations,
            "population_individuals_checked": individuals, "elite_carries_checked": elite_checks,
            "raw_final_and_control_observations_recomputed": final_observations,
            "scope": "actual stored records; optimizer fitness raw CIC outcomes were not retained"}


def make_figures(destination: Path, profiles: list[dict], panel_rows: list[dict], summaries: list[dict],
                 results: dict, rows: list[dict]) -> list[str]:
    """Create standalone scientific figures, saved as SVG and PNG."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    lookup = {s["profile_id"]: s for s in summaries}
    figures = destination/"figures"
    figures.mkdir(exist_ok=True)
    paths = []
    def save(fig, name):
        fig.tight_layout()
        for extension in ("png", "svg"):
            path = figures/f"{name}.{extension}"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            paths.append(path.relative_to(destination).as_posix())
        plt.close(fig)
    for factor in FACTORS:
        members = sorted((p for p in profiles if any(v["profile_id"] == p["profile_id"] and v["factor"] == factor for v in panel_rows)),
                         key=lambda p: p["parameters"][factor])
        x = [p["parameters"][factor] for p in members]
        values = [lookup[p["profile_id"]] for p in members]
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
        y = [s["mean_over_GA_runs"] for s in values]
        axes[0].errorbar(x, y, yerr=[s["GA_run_CI95_half_width"] for s in values], fmt="o-", capsize=4)
        for i, p in enumerate(members):
            vals = [r["independent_mean"] for r in rows if r["profile_id"] == p["profile_id"]]
            axes[0].scatter([x[i]]*len(vals), vals, s=14, alpha=.5)
        axes[0].set_ylabel("Final rumor mean (lower is better)")
        axes[0].set_title("5 GA runs; approximate 95% t CI")
        axes[1].errorbar(x, [s["mean_selection_seconds"] for s in values],
                         yerr=[s["std_selection_seconds"] for s in values], fmt="o-", capsize=4)
        axes[1].set_ylabel("Selection runtime (s)")
        axes[1].set_title("Mean +/- between-run SD")
        axes[2].plot(x, [s["mean_optimization_evaluator_calls"] for s in values], "o-")
        axes[2].set_ylabel("Actual MC fitness evaluator calls")
        axes[2].set_title("100 CIC simulations / evaluator call")
        for ax in axes:
            ax.set_xlabel(factor)
            ax.set_xticks(x)
            ax.grid(alpha=.25)
        fig.suptitle(f"email-Eu-core R=[926], k=5, p=.03: {factor}")
        save(fig, factor)
        fig, ax = plt.subplots(figsize=(7, 4))
        for p in members:
            selected = [result for result in results.values() if result["row"]["profile_id"] == p["profile_id"]]
            histories = [r["core_GA_result"]["history"] for r in selected]
            generations = range(len(histories[0]))
            ax.plot(list(generations), [mean(h[g]["best_so_far_fitness"] for h in histories) for g in generations],
                    label=f"{factor}={p['parameters'][factor]}")
        ax.set(xlabel="Generation (0 = initialization)", ylabel="Mean best training fitness", title="Training convergence; not independent quality")
        ax.legend(); ax.grid(alpha=.25)
        save(fig, f"{factor}_convergence")
    fig, ax = plt.subplots(figsize=(7, 4))
    histories = [r["core_GA_result"]["history"] for r in results.values() if r["row"]["profile_id"] == "reference"]
    for i, history in enumerate(histories):
        ax.plot([h["generation"] for h in history], [h["best_so_far_fitness"] for h in history], alpha=.7, label=f"Run {i}")
    ax.set(xlabel="Generation", ylabel="Best training fitness", title="Reference convergence: independent GA runs")
    ax.legend(); ax.grid(alpha=.25)
    save(fig, "reference_convergence")
    fig, ax = plt.subplots(figsize=(9, 5))
    for s in summaries:
        ax.errorbar(s["mean_selection_seconds"], s["mean_over_GA_runs"], yerr=s["GA_run_CI95_half_width"], fmt="o", capsize=3)
        ax.annotate(s["profile_id"], (s["mean_selection_seconds"], s["mean_over_GA_runs"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set(xlabel="Mean selection runtime (s)", ylabel="Independent final rumor mean", title="Exploratory quality / cost; 95% GA-run CIs")
    ax.grid(alpha=.25)
    save(fig, "quality_vs_cost")
    return paths


def analyze(root: Path, destination: Path, figures: bool = True) -> dict:
    """Regenerate compact exports from immutable run checkpoints, including skipped rows."""
    started = perf_counter()
    plan = json.loads((root/"frozen_plan.json").read_text())
    state = json.loads((root/"checkpoint.json").read_text())
    results, control_batches, all_payloads = {}, {}, []
    for work_id, path in state["completed"].items():
        if sha256_file(Path(path)) != state["result_sha256"][work_id]:
            raise ValueError("Completed result changed")
        result = json.loads(Path(path).read_text())
        all_payloads.append(result)
        if work_id.startswith("control_"):
            control_batches[(result["row"]["repetition_index"], result["batch"])] = result
        else:
            results[work_id] = result
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination/"observed_artifact_audit.json", audit_observed(plan, results, control_batches))
    controls, control_rows = {}, []
    node_count = round(plan["scenario"]["reachable_count"]/plan["scenario"]["reachable_fraction_of_graph"])
    for repeat in range(5):
        batches = [control_batches.get((repeat, b)) for b in range(plan["protocol"]["final_batches"])]
        if all(batches):
            counts = [n for b in batches for n in b["rumor_counts"]]
            controls[repeat] = observation_summary(counts, node_count)
            control_rows.append({"repetition_index": repeat, **controls[repeat], "runtime_seconds": sum(b["runtime_seconds"] for b in batches)})
    rows, histories, batches_export = [], [], []
    (destination/"runs").mkdir(exist_ok=True)
    for row in plan["matrix"]:
        result = results.get(row["run_id"])
        if result:
            record = row_summary(result, controls.get(row["repetition_index"]))
            for h in result["core_GA_result"]["history"]:
                histories.append({"run_id": row["run_id"], "profile_id": row["profile_id"], "repetition_index": row["repetition_index"],
                                  **{k: v for k, v in h.items() if k not in ("population", "fitness_values")}})
            for b in result["final_batches"]:
                batches_export.append({"run_id": row["run_id"], "profile_id": row["profile_id"], "repetition_index": row["repetition_index"],
                                       "batch": b["batch"], "base_seed": b["base_seed"], "runtime_seconds": b["runtime_seconds"], **b["statistics"]})
            atomic_json(destination/"runs"/f"{row['run_id']}.json", {**record, "convergence": result["core_GA_result"]["history"],
                        "final_batches": [{k: v for k, v in b.items() if k != "rumor_counts"} for b in result["final_batches"]]})
        else:
            attempts = [a for a in state["attempts"] if a["work_id"] == row["run_id"]]
            record = {**row, "status": "failed" if attempts else "skipped", "reason": state.get("stop_reason", "not_yet_executed"),
                      "protector_seeds": None, "independent_mean": None}
            atomic_json(destination/"runs"/f"{row['run_id']}.json", record)
        rows.append(record)
    summaries = []
    for profile in plan["profiles"]:
        group = [r for r in rows if r["profile_id"] == profile["profile_id"] and r["status"] == "completed"]
        if len(group) < 2:
            continue
        means, ses = [r["independent_mean"] for r in group], [r["independent_MC_SE"] for r in group]
        s = {"profile_id": profile["profile_id"], **profile["parameters"], **variance_components(means, ses),
             "std_across_GA_run_means": stdev(means),
             "mean_conditional_MC_SE": mean(ses), "mean_training_fitness": mean(r["training_fitness"] for r in group),
             "mean_final_minus_training": mean(r["independent_minus_training"] for r in group),
             "mean_selection_seconds": mean(r["selection_runtime_seconds"] for r in group),
             "std_selection_seconds": stdev(r["selection_runtime_seconds"] for r in group),
             "mean_final_evaluation_seconds": mean(r["final_evaluation_runtime_seconds"] for r in group),
             "mean_optimization_evaluator_calls": mean(r["optimization_evaluator_calls"] for r in group),
             "total_optimization_evaluator_calls": sum(r["optimization_evaluator_calls"] for r in group),
             "total_CIC_simulations": sum(r["CIC_simulations"] for r in group),
             "mean_cache_hits": mean(r["cache_hits"] for r in group),
             "unique_best_protector_sets": len({tuple(r["protector_seeds"]) for r in group}),
             "mean_pairwise_best_set_jaccard": mean(jaccard(a["protector_seeds"], b["protector_seeds"])
                 for i, a in enumerate(group) for b in group[i+1:]),
             "mean_spread_reduction_fraction": mean(r["spread_reduction_fraction"] for r in group) if all(r["spread_reduction_fraction"] is not None for r in group) else None}
        s["GA_run_CI95_half_width"] = (s["CI95_over_GA_run_means_high"]-s["CI95_over_GA_run_means_low"])/2
        summaries.append(s)
    contrasts, contrast_pairs = [], []
    for profile in plan["profiles"]:
        if profile["profile_id"] == "reference":
            continue
        diffs, ses = [], []
        for rep in range(5):
            a = next((r for r in results.values() if r["row"]["profile_id"] == profile["profile_id"] and r["row"]["repetition_index"] == rep), None)
            b = next((r for r in results.values() if r["row"]["profile_id"] == "reference" and r["row"]["repetition_index"] == rep), None)
            if a is None or b is None:
                continue
            ca = [v for batch in a["final_batches"] for v in batch["rumor_counts"]]
            cb = [v for batch in b["final_batches"] for v in batch["rumor_counts"]]
            paired = paired_differences(ca, cb)
            differences = [x-y for x, y in zip(ca, cb)]
            mcse = stdev(differences)/sqrt(len(differences))
            difference = a["final"]["rumor_mean"]-b["final"]["rumor_mean"]
            diffs.append(difference); ses.append(mcse)
            contrast_pairs.append({"profile_id": profile["profile_id"], "factor": profile["changed_factor"],
                                   "repetition_index": rep, "difference": difference, "conditional_MC_SE_of_difference": mcse,
                                   "conditional_paired_MC_diagnostics": paired})
        if len(diffs) >= 2:
            contrasts.append({"profile_id": profile["profile_id"], "factor": profile["changed_factor"],
                              "level": profile["parameters"][profile["changed_factor"]], **contrast_summary(diffs, ses)})
    counts = Counter(r["status"] for r in rows)
    ga_payloads = list(results.values())
    control_payloads = list(control_batches.values())
    selection = sum(r["selection_runtime_seconds"] for r in ga_payloads)
    final = sum(r["final_evaluation_runtime_seconds"] for r in ga_payloads)
    control_time = sum(r["runtime_seconds"] for r in control_payloads)
    loading = sum(r["graph_loading_seconds"] for r in all_payloads)
    worker_time = sum(r["worker_runtime_seconds"] for r in all_payloads)
    attempt_time = sum(a["elapsed_seconds"] for a in state["attempts"])
    runtime = {"selection_optimization_seconds": selection,
               "fitness_MC_seconds_subset_of_selection": sum(r["fitness_evaluator_runtime_seconds"] for r in ga_payloads),
               "GA_final_evaluation_seconds": final, "shared_control_evaluation_seconds": control_time,
               "graph_loading_seconds": loading, "worker_other_seconds": worker_time-selection-final-control_time-loading,
               "process_startup_and_output_seconds": attempt_time-worker_time,
               "parent_overhead_seconds": state.get("parent_overhead_seconds", 0.0),
               "total_active_experiment_seconds": state["active_runtime_seconds"],
               "definition": "active subprocess wall + parent orchestration; idle paused time excluded; test/analysis runtimes separate"}
    summary = {"status": state["status"], "planned_GA_runs": 45, "completed_GA_runs": counts["completed"],
               "failed_GA_runs": counts["failed"], "skipped_GA_runs": counts["skipped"],
               "failed_or_interrupted_attempts": sum(a["status"] != "completed" for a in state["attempts"]),
               "control_evaluator_calls": len(control_payloads),
               "optimization_evaluator_calls": sum(r["core_GA_result"]["evaluation_count"] for r in ga_payloads),
               "GA_final_evaluator_calls": sum(r["row"]["final_batches"] for r in ga_payloads),
               "total_actual_evaluator_calls": sum(r["evaluator_calls"] for r in all_payloads),
               "optimization_CIC_simulations": sum(r["core_GA_result"]["cic_simulation_count"] for r in ga_payloads),
               "GA_final_CIC_simulations": sum(r["row"]["final_batches"]*r["row"]["S_eval"] for r in ga_payloads),
               "control_CIC_simulations": sum(r["CIC_simulations"] for r in control_payloads),
               "total_actual_CIC_simulations": sum(r["CIC_simulations"] for r in all_payloads),
               "conservative_charged_CIC": state["charged_CIC"],
               "cache_hits": sum(r["core_GA_result"]["cache_hit_count"] for r in ga_payloads),
               "elite_fitness_reuses": sum(r["core_GA_result"]["elite_fitness_reuse_count"] for r in ga_payloads),
               "runtime": runtime, "preflight": {k: v for k, v in plan["preflight"].items() if k != "rows"},
               "contrasts_with_family_CI_excluding_zero": sum(c["conclusion"] != "insufficient_evidence_of_difference" for c in contrasts),
               "no_main_or_full_design": True, "reserved_main_master_seed": plan["request"]["reserved_main_master_seed"],
               "reserved_validation_scenarios": plan["protocol"]["validation_scenario_ids"],
               "new_candidate_automatically_selected": False}
    for name, obj in (("run_results", rows), ("summary_by_configuration", summaries), ("contrasts", contrasts),
                      ("paired_contrasts_by_repetition", contrast_pairs), ("control_results", control_rows),
                      ("final_batches", batches_export), ("convergence", histories)):
        write_json(destination/f"{name}.json", obj)
        write_csv(destination/f"{name}.csv", obj)
    figure_paths = []
    if figures and counts["completed"] == 45:
        figure_paths = make_figures(destination, plan["profiles"], plan["panel_rows"], summaries, results, rows)
    summary["figures"] = figure_paths
    summary["analysis_runtime_seconds"] = perf_counter()-started
    atomic_json(destination/"summary.json", summary)
    atomic_json(destination/"runtime.json", runtime)
    atomic_json(destination/"metadata.json", json.loads((root/"metadata.json").read_text()))
    atomic_json(destination/"checkpoint_summary.json", {k: v for k, v in state.items() if k not in ("completed", "pending")})
    atomic_json(destination/"integrity_after.json", json.loads((root/"integrity_after.json").read_text()))
    atomic_json(destination/"raw_artifact_inventory.json", {"directory": root.relative_to(PROJECT_ROOT).as_posix(),
                "files": {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()},
                "raw_results_are_ignored_by_git": True, "compact_run_exports_include_histories_and_summaries": True})
    return summary


def report(destination: Path, target: Path) -> None:
    """Render actual numbers and limitations; pending verification stays explicit."""
    load = lambda name: json.loads((destination/f"{name}.json").read_text())
    summary, profiles, aggregates, contrasts = load("summary"), load("profiles"), load("summary_by_configuration"), load("contrasts")
    pre, rt = summary["preflight"], summary["runtime"]
    verification_path = destination/"verification.json"
    verification = json.loads(verification_path.read_text()) if verification_path.exists() else None
    rows = load("run_results")
    controls = load("control_results")
    ptable = "\n".join(f"| {p['profile_id']} | {p['parameters']['population_size']} | {p['parameters']['max_generations']} | {p['parameters']['crossover_rate']} | {p['parameters']['mutation_rate']} | 5 |" for p in profiles)
    resulttable = "\n".join(f"| {s['profile_id']} | {s['mean_training_fitness']:.3f} | {s['mean_over_GA_runs']:.3f} ± {s['std_across_GA_run_means']:.3f} | [{s['CI95_over_GA_run_means_low']:.3f}, {s['CI95_over_GA_run_means_high']:.3f}] | {s['mean_conditional_MC_SE']:.3f} | {s['mean_selection_seconds']:.2f} | {s['mean_optimization_evaluator_calls']:.1f} |" for s in aggregates)
    panels = []
    factor_titles = {"population_size": "Population size", "max_generations": "Generations", "crossover_rate": "Crossover rate", "mutation_rate": "Mutation rate"}
    a = {s["profile_id"]: s for s in aggregates}
    observations = {
        "population_size": f"Final means N10/N20/N40 lần lượt {a['reference']['mean_over_GA_runs']:.3f}/{a['population_size_20']['mean_over_GA_runs']:.3f}/{a['population_size_40']['mean_over_GA_runs']:.3f}. N40 cần khoảng {a['population_size_40']['mean_selection_seconds']/a['reference']['mean_selection_seconds']:.2f} lần selection runtime của reference; N20 khoảng {a['population_size_20']['mean_selection_seconds']/a['reference']['mean_selection_seconds']:.2f} lần. Đây là trade-off mô tả để xác nhận tiếp, chưa phải kết luận vượt trội.",
        "max_generations": f"Final means G10/G20/G40 lần lượt {a['reference']['mean_over_GA_runs']:.3f}/{a['max_generations_20']['mean_over_GA_runs']:.3f}/{a['max_generations_40']['mean_over_GA_runs']:.3f}; SD giữa runs {a['reference']['std_across_GA_run_means']:.3f}/{a['max_generations_20']['std_across_GA_run_means']:.3f}/{a['max_generations_40']['std_across_GA_run_means']:.3f}. Cache khiến actual fitness calls chỉ {a['reference']['mean_optimization_evaluator_calls']:.1f}/{a['max_generations_20']['mean_optimization_evaluator_calls']:.1f}/{a['max_generations_40']['mean_optimization_evaluator_calls']:.1f} mỗi run, thấp hơn nhiều uncached bounds. Không suy ra tăng G chắc chắn cải thiện hoặc làm xấu chất lượng từ các mean này.",
        "crossover_rate": f"Final means crossover0.6/0.8/1.0 lần lượt {a['crossover_rate_0p6']['mean_over_GA_runs']:.3f}/{a['reference']['mean_over_GA_runs']:.3f}/{a['crossover_rate_1']['mean_over_GA_runs']:.3f}. Không dùng training means hoặc vị trí thấp nhất của đường mean để chốt crossover tối ưu.",
        "mutation_rate": f"Final means mutation0.05/0.1/0.2 lần lượt {a['mutation_rate_0p05']['mean_over_GA_runs']:.3f}/{a['reference']['mean_over_GA_runs']:.3f}/{a['mutation_rate_0p2']['mean_over_GA_runs']:.3f}; selection runtime {a['mutation_rate_0p05']['mean_selection_seconds']:.2f}/{a['reference']['mean_selection_seconds']:.2f}/{a['mutation_rate_0p2']['mean_selection_seconds']:.2f} s/run. Khác biệt mô tả không chứng minh winner hoặc equivalence.",
    }
    for factor in FACTORS:
        group = [c for c in contrasts if c["factor"] == factor]
        table = "\n".join(f"| {c['level']} | {c['mean_difference']:+.3f} | [{c['pointwise_CI95_low']:+.3f}, {c['pointwise_CI95_high']:+.3f}] | [{c['Bonferroni_family_CI95_low']:+.3f}, {c['Bonferroni_family_CI95_high']:+.3f}] | {c['conclusion']} |" for c in group)
        panels.append(f"""### {factor_titles[factor]}

Mỗi hàng so với reference, cùng R/k/p/tie/S và quy trình final evaluation.
Delta = alternative − reference; số âm là ít rumor hơn. Đây là hiệu ứng trên
một scenario development, chưa phải hiệu ứng tổng quát trên các dataset.

| Mức | Delta mean | CI95 pointwise | CI95 Bonferroni (8 contrasts) | Diễn giải |
|---|---:|---|---|---|
{table}

{observations[factor]}

![{factor_titles[factor]}](docs/milestone_7_reduced_screen_v2/figures/{factor}.png)

[Training convergence theo panel](docs/milestone_7_reduced_screen_v2/figures/{factor}_convergence.png).
""")
    test_text = (f"{verification['tests_passed']}/{verification['tests_run']} tests pass; "
                 f"{verification['protected_files_checked']} protected files và {verification['data_files_checked']} data files không đổi."
                 if verification else "Final tests/checksum verification đang chờ; xem verification.json sau khi hoàn tất.")
    unresolved = all(c["conclusion"] == "insufficient_evidence_of_difference" for c in contrasts)
    candidate_text = ("Chưa đủ bằng chứng để thay reference bằng một mức tham số khác. Giữ N=10, G=10, crossover=0.8, mutation=0.1, tournament=3, elitism=1, cache=True làm ứng viên tham chiếu để kiểm tra tiếp trên dataset/scenario khác. Đây là lựa chọn tiết kiệm có điều kiện, không phải tham số tối ưu." if unresolved else
        "Có contrast thăm dò có CI hiệu chỉnh không chứa 0; chỉ ghi nhận trong scenario email R926, xem bảng từng panel. Chưa tự chốt winner hoặc thay protocol main; reference vẫn là mốc để xác nhận trên dataset/scenario khác. Các profile có bằng chứng thăm dò cần được xác nhận độc lập trước khi sử dụng.")
    target.write_text(f"""# Milestone 7 – Reduced GA Parameter Screening V2

Trạng thái: **{summary['status']}**, {summary['completed_GA_runs']}/45 GA runs thành công,
{summary['failed_GA_runs']} thất bại, {summary['skipped_GA_runs']} skipped;
{summary['failed_or_interrupted_attempts']} interrupted/failed attempts.
Không chạy Full Design hoặc main experiments. Số liệu dưới đây đã chạy thực tế,
trừ các hàng ghi rõ projected/upper bound. V2 không ghi đè kết quả preflight cũ.

## 1. Audit ma trận trước và phạm vi OFAT

Blueprint của Protocol v1 có 9 cấu hình duy nhất. Reduced subset cũ lấy 5:
reference, population20, generations20, crossover0.6, mutation0.2, và **lặp đủ
5 profile trên mỗi** email R926, Facebook R1180, Wiki R1210. Không chia 9
profile thành 3 phần rồi phân cho 3 dataset. Mỗi scenario có 25 planned runs,
tổng 75, tất cả skipped tại preflight runtime 10.985,164 > 10.800 giây.

| Scenario cũ | Population levels | Generations levels | Crossover levels | Mutation levels | Đủ ba mức? |
|---|---|---|---|---|---|
| email-Eu-core R=[926] | 10,20 | 10,20 | 0.6,0.8 | 0.1,0.2 | Không panel nào |
| ego-Facebook R=[1180] | 10,20 | 10,20 | 0.6,0.8 | 0.1,0.2 | Không panel nào |
| Wiki-Vote R=[1210] | 10,20 | 10,20 | 0.6,0.8 | 0.1,0.2 | Không panel nào |

Audit 60 planned pairs: không pair nào đổi dataset, R hoặc biến cố định khác;
chỉ đối chiếu reference với đúng một thay đổi. Bốn panel có thể phân tích
two-level contrasts **trong từng scenario nếu đã chạy**; vì 0 completed runs
nên chưa có phân tích thực nghiệm nào từ matrix cũ. Không ghép kết quả khác
dataset để suy ra ảnh hưởng riêng của tham số. File: [audit_previous.json](docs/milestone_7_reduced_screen_v2/audit_previous.json).

## 2. Ma trận V2 đã cố định trước khi chạy

**9 profiles × 1 scenario × 5 independent GA runs =45 tổng.** Reference chỉ
chạy 5 lần rồi dùng chung cho cả bốn panel (12 panel rows, không phải 60 runs).
Các tham số không khảo sát giữ nguyên reference Protocol v1.

| Profile | N | G | Crossover | Mutation | Repeats |
|---|---:|---:|---:|---:|---:|
{ptable}

Điều kiện chung: email-Eu-core, R=[926], k=5, p=0.03,
tie=protector-priority, tournament=3, elitism=1, cache=True; S_opt=100;
S_eval=6.000/batch và B=2, tức 12.000 final CIC simulations cho mỗi P.
[Matrix 45 dòng đầy đủ seed labels](docs/milestone_7_reduced_screen_v2/matrix.csv),
[request JSON](experiments/configs/milestone_7_reduced_screen_v2.json).
Không sửa reference hoặc factor levels trong Protocol v1.
Authorization flag lịch sử trong v1 không được sửa; quyền chạy V2 có điều kiện
đến từ yêu cầu mới của người dùng, và preflight đã đạt trước run đầu.

Chọn scenario từ topology/No Intervention của Pilot 2: R926 reachable=965/1.005,
bao gồm seed; No Intervention tại p=.03, S=200 có mean=34.68, std=88.829,
SE=6.297, rumor fraction=3.451%. Đây là representative đã xác định trước,
đạt control gate [2%,80%] số nút và dưới 90% reachable. Không dùng score GA
để chọn R/p. 75.5% Pilot-2 observations không lan ngoài seed cho thấy phân bố
còn nhiều zero-growth events; không khẳng định scenario này đại diện mọi R.
Low-reach scenarios vẫn được giữ trong manifest cho phân tích bổ sung.

Seed master V2=2026111110, tách pilot=2026111107, preflight cũ=2026111108 và
reserved main=2026111109. Block width=1.000.000, Cantor(master,index) như runner
đã kiểm chứng. Optimization index=(scenario_index+1)*10000+profile_ordinal*100+repeat:
45 bộ optimizer/fitness seed riêng. Mỗi GA dùng một fitness schedule cố định
100 seeds và cache cục bộ; elite giữ nguyên fitness theo GA hiện có.
Final index=scenario_index*100+repeat, sử dụng nửa final của block, hai batch
liền kề 6.000 seeds. Final schedules giống nhau giữa profiles trong cùng repeat,
khác giữa repeats và không giao bất kỳ optimization interval nào. Cùng final
seed không bảo đảm từng edge có cùng random outcome vì số valid attempts phụ
thuộc P. Khác seed optimizer giữa profiles là replication theo cùng policy,
không phải đổi điều kiện nghiên cứu OFAT.

Ma trận và policy phân tích đã đóng băng trước run đầu. Với từng run, chọn
và khóa P trước final evaluation; final không được trả về optimizer và không
được dùng để sửa matrix. Shared No Intervention chỉ chạy sau tất cả GA runs.
V2 đánh giá final ngay sau từng GA, khác selection-barrier của pilot cũ nhưng
không có adaptation/cross-run fitness reuse hoặc thay đổi semantics.

## 3. Computational preflight và chi phí đo thực tế

Bound fitness calls mỗi run: U=N+G(N−elitism), không tính cache hits/elite
carries là evaluator calls. Sum U của 9 profiles=1.700, nhân 5 repeats=8.500.

| Thành phần | Evaluator calls upper | CIC simulations upper |
|---|---:|---:|
| Optimization, S_opt100 | 8.500 | 850.000 |
| Final, 45×2×6.000 | 90 | 540.000 |
| Shared controls, 5×2×6.000 | 10 | 60.000 |
| Tổng | 8.600 | 1.450.000 |

Pilot-2 email rates: fitness=0.001189884 s/CIC, final=0.001293115 s/CIC,
control=0.000323939 s/CIC, cộng non-MC history cost. Đây là measured source rates
trên một R, **không phải thời gian V2 đã đo hoặc hard upper bound**.
Projection trước safety={pre['rate_projection_seconds_before_safety']:.3f} s;
nhân 1.5={pre['rate_projection_seconds_with_safety']:.3f} s, thêm allowance
loading/export/setup 300 s thành **{pre['projected_seconds_including_overhead']:.3f} s**.
Headroom so với cap 10.800 s={10800-pre['projected_seconds_including_overhead']:.3f} s.
Count caps: 120 GA runs, 3.000.000 CIC; schedule V2 chỉ cho phép 45 planned GA.
Timeout một worker tối đa 600 s, luôn cắt theo active budget còn lại.

**Đã đo**: {summary['optimization_evaluator_calls']} fitness calls + {summary['GA_final_evaluator_calls']} final calls
+ {summary['control_evaluator_calls']} control calls = {summary['total_actual_evaluator_calls']} evaluator calls;
{summary['total_actual_CIC_simulations']:,} CIC simulations, gồm
{summary['optimization_CIC_simulations']:,} optimization + {summary['GA_final_CIC_simulations']:,} final
+ {summary['control_CIC_simulations']:,} control; cache hits={summary['cache_hits']},
elite fitness reuses={summary['elite_fitness_reuses']}.

| Runtime component, đã đo | Giây |
|---|---:|
| Selection/optimization | {rt['selection_optimization_seconds']:.3f} |
| Fitness MC (đã nằm trong selection, không cộng lần hai) | {rt['fitness_MC_seconds_subset_of_selection']:.3f} |
| Independent GA final evaluation | {rt['GA_final_evaluation_seconds']:.3f} |
| Shared controls | {rt['shared_control_evaluation_seconds']:.3f} |
| Graph loading | {rt['graph_loading_seconds']:.3f} |
| Worker bookkeeping/graph copy/statistics | {rt['worker_other_seconds']:.3f} |
| Process startup/output | {rt['process_startup_and_output_seconds']:.3f} |
| Parent orchestration | {rt['parent_overhead_seconds']:.3f} |
| **Tổng active experiment runtime** | **{rt['total_active_experiment_seconds']:.3f}** |

Test/analysis/plotting runtime báo riêng, không giả làm algorithm runtime.
Checkpoint ghi atomic sau từng unit; resume chỉ tiếp tục cùng fingerprint
code/data/config, xác minh SHA256 result hoàn tất và bỏ qua units đã lưu.
Nếu bị gián đoạn trước khi publish result thì charge conservatively upper
CIC và timeout, không ghi unknown work=0. Cumulative budget không reset khi resume.
Raw checkpoints/counts và full GA records ở results/milestone_7_reduced_screen_v2
(gitignored); compact CSV/JSON/history được lưu trong docs và inventory có hashes.

## 4. Chất lượng, ổn định và ảnh hưởng từng tham số

SD giữa 5 GA-run means **có cả MC noise**; conditional MC SE chỉ đo bất định
ước lượng với một P cố định. CI qua GA runs dùng t(df=4), tính xấp xỉ với n=5,
không phải 60.000 independent GA repetitions.

| Profile | Training mean | Final mean ± between-run SD | CI95 qua GA runs | Mean conditional MC SE | Selection s/run | Fitness calls/run |
|---|---:|---|---|---:|---:|---:|
{resulttable}

No Intervention mới, cùng final seeds: mean qua 5 batches-pairs={mean(c['rumor_mean'] for c in controls):.3f}.
Spread reductions có trong run_results.csv; đây là kiểm chứng phạm vi screen,
không phải benchmark GA với các baseline hay kết quả chính thức của đồ án.

{''.join(panels)}
## 5. Hội tụ, fitness noise và giới hạn diễn giải

![Reference convergence](docs/milestone_7_reduced_screen_v2/figures/reference_convergence.png)

![Quality and cost](docs/milestone_7_reduced_screen_v2/figures/quality_vs_cost.png)

Convergence.csv/json có generation0 đến đúng G, best/mean fitness, selected P,
cache counters và thời gian. Training fitness dùng fixed schedule nhỏ, đã được
tối ưu trực tiếp nên có thể lạc quan. Không dùng đường training làm final quality.
Run-level training–independent gap và hai batch conditional CIs được lưu riêng.
Đường của G20/G40 không phải phần nối tiếp một G10 run vì optimizer seeds riêng.

Tám planned contrasts là alt−reference, paired theo repeat/final schedule.
Pointwise CI95 và simultaneous Bonferroni CI95 (family tám contrasts) đều được
lưu. Chỉ diễn giải khác biệt nếu interval hiệu chỉnh loại 0; interval chứa 0
nghĩa là **chưa đủ bằng chứng**, không phải tương đương. Năm pairs nhỏ và rumor
skew làm t intervals chỉ có tính thăm dò, chưa bảo đảm coverage.
Số contrasts với CI family loại 0: {summary['contrasts_with_family_CI_excluding_zero']}/8.
Không kiểm định thêm mọi cặp giữa hai alternative levels; không suy ra khác
biệt N20−N40 từ việc một contrast với reference có ý nghĩa còn contrast kia
không. Chưa chốt ngưỡng practical significance hoặc equivalence margin.

Variance decomposition giữ raw Var(GA means)−mean(MC SE²), đồng thời có display
clipped>=0; giá trị âm không chứng minh GA hết biến động. Với contrasts, MC
variance dùng seed-aligned raw differences; không giả định independent errors
giữa hai profiles dùng chung final seeds. Genotype stability có unique P count
và pairwise Jaccard trong summary_by_configuration. Không ước lượng interaction
giữa factors bằng OFAT, không kết hợp các mức tốt nhất thành cấu hình chưa thử.

## 6. Ứng viên tiếp theo, kiểm chứng và dữ liệu xuất

{candidate_text}

| Ứng viên cần xác nhận ở development scenarios khác | Vai trò | Mức chắc chắn hiện tại |
|---|---|---|
| N10/G10/crossover0.8/mutation0.1 | Giữ reference đã có, chi phí thấp | Khả thi trên R926; chưa xác nhận tối ưu |
| N20/G10/crossover0.8/mutation0.1 | Kiểm tra trade-off trung gian, chỉ đổi N | Thăm dò; CI effect còn chứa 0 |
| N40/G10/crossover0.8/mutation0.1 | Kiểm tra mean giảm mô tả có tái hiện với chi phí cao hơn không | Thăm dò; CI effect còn chứa 0 |

Bảng này không cấp quyền chạy thêm hoặc tự chọn N20/N40 cho main. Mọi bước
xác nhận khác dataset phải có preflight riêng; không ghép các outcomes đó để
suy ra một population effect thuần túy khi R/graph khác. Chưa có ứng viên mới
cho G/crossover/mutation đủ bằng chứng để thay reference.

Độ chắc chắn về khả năng thực thi: có số liệu V2 ở một scenario. Độ chắc chắn
về chất lượng tổng quát: còn thấp vì chỉ email/high-reach R926, một k/p, 5 runs,
fixed training seeds và nhiều zero-growth events. Cần xác nhận trên development
scenarios khác với namespace mới trước khi chốt GA; không dùng validation/main
holdouts để tiếp tục tuning. Reserved R858/1555/2110 và main master vẫn chưa dùng
trong V2. Các low/legacy scenarios còn trong manifest để phân tích bổ sung.

{test_text}
IC/CIC/Monte Carlo/Greedy/GA và Protocol-v1 JSON không đổi. Không chạy main
experiments, Full Design, Facebook/Wiki parameter sweep hoặc tự tăng budget.

Đầu ra chính: [summary.json](docs/milestone_7_reduced_screen_v2/summary.json),
[run_results.csv](docs/milestone_7_reduced_screen_v2/run_results.csv),
[summary_by_configuration.csv](docs/milestone_7_reduced_screen_v2/summary_by_configuration.csv),
[contrasts.csv](docs/milestone_7_reduced_screen_v2/contrasts.csv),
[convergence.csv](docs/milestone_7_reduced_screen_v2/convergence.csv),
[final_batches.csv](docs/milestone_7_reduced_screen_v2/final_batches.csv),
[runtime.json](docs/milestone_7_reduced_screen_v2/runtime.json).
Mỗi run có JSON riêng trong docs/milestone_7_reduced_screen_v2/runs.

Chạy/tiếp tục cùng matrix:
```sh
.venv/bin/python -B -m experiments.reduced_screen_v2 --phase preflight
.venv/bin/python -B -u -m experiments.reduced_screen_v2 --phase run
.venv/bin/python -B -m experiments.analyze_reduced_screen_v2
.venv/bin/python -B -m unittest discover -s tests -q
```
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT/"results/milestone_7_reduced_screen_v2")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT/"docs/milestone_7_reduced_screen_v2")
    args = parser.parse_args(argv)
    summary = analyze(args.root, args.output)
    if summary["completed_GA_runs"] == 45:
        report(args.output, PROJECT_ROOT/"MILESTONE_7_REDUCED_SCREEN_V2.md")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("figures", "preflight")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
