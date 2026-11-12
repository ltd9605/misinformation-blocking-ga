"""Analyze confirmation within each dataset; never pool effects or run main."""

import argparse
from collections import Counter
import json
from math import sqrt
import os
from pathlib import Path
from statistics import mean, stdev
from tempfile import gettempdir
from time import perf_counter

os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir())/"misinformation-confirmation-matplotlib"))

from experiments.analyze_reduced_screen_v2 import audit_observed, contrast_summary, row_summary
from experiments.pilot_protocol_validation import write_csv
from experiments.reduced_screen_v2 import atomic_json
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.calibration import jaccard, observation_summary, paired_differences
from src.experiments.sensitivity import variance_components


def aggregate_dataset(rows: list[dict]) -> list[dict]:
    """One mean per GA run, grouped by dataset/profile, with no cross-graph pooling."""
    summaries = []
    for dataset in sorted({r["dataset"] for r in rows}):
        for pop in (10, 20, 40):
            group = [r for r in rows if r["dataset"] == dataset and r["population_size"] == pop and r["status"] == "completed"]
            if len(group) < 2:
                continue
            values = [r["independent_mean"] for r in group]
            ses = [r["independent_MC_SE"] for r in group]
            summaries.append({"dataset": dataset, "scenario_id": group[0]["scenario_id"], "rumor_seeds": group[0]["rumor_seeds"],
                              "profile_id": group[0]["profile_id"], "population_size": pop,
                              **variance_components(values, ses), "std_across_GA_run_means": stdev(values),
                              "mean_conditional_MC_SE": mean(ses), "max_conditional_MC_SE": max(ses),
                              "mean_training_fitness": mean(r["training_fitness"] for r in group),
                              "mean_final_minus_training": mean(r["independent_minus_training"] for r in group),
                              "mean_selection_seconds": mean(r["selection_runtime_seconds"] for r in group),
                              "std_selection_seconds": stdev(r["selection_runtime_seconds"] for r in group),
                              "mean_final_evaluation_seconds": mean(r["final_evaluation_runtime_seconds"] for r in group),
                              "mean_optimization_evaluator_calls": mean(r["optimization_evaluator_calls"] for r in group),
                              "total_optimization_evaluator_calls": sum(r["optimization_evaluator_calls"] for r in group),
                              "total_CIC_simulations": sum(r["CIC_simulations"] for r in group),
                              "mean_cache_hits": mean(r["cache_hits"] for r in group),
                              "unique_best_sets": len({tuple(r["protector_seeds"]) for r in group}),
                              "mean_best_set_Jaccard": mean(jaccard(a["protector_seeds"], b["protector_seeds"])
                                  for i, a in enumerate(group) for b in group[i+1:])})
    return summaries


def configuration_decision(summary: dict, contrasts: list[dict]) -> dict:
    """Recommend retaining or reviewing reference, never equate nonsignificance with equivalence."""
    complete = summary["completed_GA_runs"] == 27
    resolved = [c for c in contrasts if c["conclusion"] != "insufficient_evidence_of_difference"]
    alternatives_lower = [c for c in resolved if c["conclusion"].startswith("lower_final_rumor")]
    return {"status": "proposal_not_a_main_protocol_lock", "confirmation_complete": complete,
            "decision": ("insufficient_completed_runs" if not complete else "review_reference_before_main_lock" if alternatives_lower else "retain_reference_as_practical_candidate"),
            "family_CI_resolved_contrasts": len(resolved), "configurations_proven_equivalent": False,
            "contrasts_favoring_alternatives_requiring_review": len(alternatives_lower),
            "globally_optimal_GA_configuration_identified": False, "cross_dataset_effects_pooled": False,
            "automatic_change_to_reference": False, "main_experiments_authorized": False,
            "reason": "n=3 per configuration/scenario cannot establish generality or equivalence; retain the predeclared reference unless evidence warrants a separately reviewed revision"}


def audit_main_reservations(plan: dict) -> dict:
    """Verify reserved R do not overlap known earlier rumor scenarios or this stage."""
    used = {d: set() for d in plan["protocol"]["datasets"]}
    for scenario in plan["old_scenarios"]:
        used[scenario["dataset"]].update(scenario["rumor_seeds"])
    prior = json.loads((PROJECT_ROOT/"docs/pilot_protocol_validation/rumor_scenarios.json").read_text())
    for dataset, scenario in prior.items():
        used[dataset].update(scenario["rumor_seeds"])
    used["email-Eu-core"].add(0)  # IC/CIC/GA/runner email smoke configurations.
    for scenario in plan["main_reservations"]:
        if set(scenario["rumor_seeds"]) & used[scenario["dataset"]]:
            raise ValueError("A main reservation overlaps an earlier rumor seed")
        if any(row["dataset"] == scenario["dataset"] and set(row["rumor_seeds"]) & set(scenario["rumor_seeds"]) for row in plan["matrix"]):
            raise ValueError("A main R was included in the confirmation matrix")
    return {"earlier_known_R_by_dataset": {d: sorted(v) for d, v in used.items()},
            "reserved_R_do_not_overlap": True, "confirmation_does_not_evaluate_reserved_R": True,
            "official_MC_observations_generated": 0,
            "scope": "recorded Pilot2, Protocol Validation and earlier email smoke R; no claim that node IDs never appeared as protectors"}


def audit_one_scenario(plan: dict, scenario: dict, results: dict, controls: dict) -> dict:
    """Scope the reused single-scenario auditor to its own reference/seed rows."""
    scoped = {"scenario": scenario, "matrix": [r for r in plan["matrix"] if r["scenario_id"] == scenario["scenario_id"]]}
    return audit_observed(scoped, results, controls)


def create_figures(destination: Path, aggregates: list[dict], results: dict) -> list[str]:
    """Scientific plots for quality/cost and training convergence per scenario."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    root = destination/"figures"
    root.mkdir(exist_ok=True)
    outputs = []
    def save(fig, name):
        fig.tight_layout()
        for extension in ("png", "svg"):
            path = root/f"{name}.{extension}"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            outputs.append(path.relative_to(destination).as_posix())
        plt.close(fig)
    for dataset in sorted({r["dataset"] for r in aggregates}):
        group = sorted([s for s in aggregates if s["dataset"] == dataset], key=lambda s: s["population_size"])
        x = [s["population_size"] for s in group]
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
        y = [s["mean_over_GA_runs"] for s in group]
        axes[0].errorbar(x, y, yerr=[(s["CI95_over_GA_run_means_high"]-s["CI95_over_GA_run_means_low"])/2 for s in group], fmt="o-", capsize=4)
        axes[0].set(ylabel="Independent final rumor mean", title="3 GA runs; approximate 95% t CI")
        axes[1].errorbar(x, [s["mean_selection_seconds"] for s in group], yerr=[s["std_selection_seconds"] for s in group], fmt="o-", capsize=4)
        axes[1].set(ylabel="Selection runtime (seconds)", title="Mean +/- between-run SD")
        axes[2].plot(x, [s["mean_optimization_evaluator_calls"] for s in group], "o-")
        axes[2].set(ylabel="Fitness evaluator calls / GA run", title="S_opt=100; actual cache-aware work")
        for ax in axes:
            ax.set_xlabel("Population size")
            ax.set_xticks(x)
            ax.grid(alpha=.25)
        fig.suptitle(f"{dataset}, R={group[0]['rumor_seeds']}, k=5, p=.03")
        save(fig, f"{dataset}_quality_cost")
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        for pop in (10, 20, 40):
            runs = [r for r in results.values() if r["row"]["dataset"] == dataset and r["row"]["population_size"] == pop]
            histories = [r["core_GA_result"]["history"] for r in runs]
            g = list(range(len(histories[0])))
            axes[0].plot(g, [mean(h[i]["best_so_far_fitness"] for h in histories) for i in g], label=f"N={pop}")
            axes[1].plot(g, [mean(h[i]["mean_fitness"] for h in histories) for i in g], label=f"N={pop}")
        axes[0].set_ylabel("Best training fitness")
        axes[1].set_ylabel("Population mean training fitness")
        for ax in axes:
            ax.set_xlabel("Generation (0 = initialization)")
            ax.legend(); ax.grid(alpha=.25)
        fig.suptitle(f"{dataset}: training convergence, not final quality")
        save(fig, f"{dataset}_convergence")
    return outputs


def analyze(root: Path, destination: Path, figures: bool = True) -> dict:
    """Validate immutable checkpoints and export per-dataset tables and metrics."""
    started = perf_counter()
    plan = json.loads((root/"frozen_plan.json").read_text())
    state = json.loads((root/"checkpoint.json").read_text())
    results, controls, all_payloads = {}, {}, []
    for work_id, path in state["completed"].items():
        if sha256_file(Path(path)) != state["result_sha256"][work_id]:
            raise ValueError("Completed result changed")
        result = json.loads(Path(path).read_text())
        all_payloads.append(result)
        if work_id.startswith("control_"):
            controls[(result["row"]["scenario_id"], result["row"]["repetition_index"], result["batch"])] = result
        else:
            results[work_id] = result
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination/"main_holdout_prior_usage_audit.json", audit_main_reservations(plan))
    audits, pooled_controls, control_rows = [], {}, []
    for scenario in plan["scenarios"]:
        name = scenario["scenario_id"]
        subset = {k: r for k, r in results.items() if r["row"]["scenario_id"] == name}
        control_subset = {(rep, b): r for (s, rep, b), r in controls.items() if s == name}
        audits.append({"scenario_id": name, **audit_one_scenario(plan, scenario, subset, control_subset)})
        node_count = round(scenario["reachable_count"]/scenario["reachable_fraction_of_graph"])
        for repeat in range(3):
            batches = [controls.get((name, repeat, b)) for b in range(plan["protocol"]["final_batches"])]
            if all(batches):
                pooled = observation_summary([v for r in batches for v in r["rumor_counts"]], node_count)
                pooled_controls[(name, repeat)] = pooled
                control_rows.append({"dataset": scenario["dataset"], "scenario_id": name, "rumor_seeds": scenario["rumor_seeds"],
                                     "repetition_index": repeat, **pooled, "runtime_seconds": sum(b["runtime_seconds"] for b in batches)})
    rows, convergence, batch_rows = [], [], []
    (destination/"runs").mkdir(exist_ok=True)
    for row in plan["matrix"]:
        run_id = row["run_id"]
        if run_id in results:
            result = results[run_id]
            record = row_summary(result, pooled_controls.get((row["scenario_id"], row["repetition_index"])))
            record["worker_peak_RSS_bytes"] = result["worker_peak_RSS_bytes"]
            atomic_json(destination/"runs"/f"{run_id}.json", {**record, "convergence": result["core_GA_result"]["history"],
                        "final_batches": [{k: v for k, v in b.items() if k != "rumor_counts"} for b in result["final_batches"]]})
            for h in result["core_GA_result"]["history"]:
                convergence.append({"run_id": run_id, "dataset": row["dataset"], "profile_id": row["profile_id"],
                                    "repetition_index": row["repetition_index"], **{k: v for k, v in h.items() if k not in ("population", "fitness_values")}})
            for b in result["final_batches"]:
                batch_rows.append({"run_id": run_id, "dataset": row["dataset"], "profile_id": row["profile_id"],
                                   "repetition_index": row["repetition_index"], "batch": b["batch"], "base_seed": b["base_seed"],
                                   "runtime_seconds": b["runtime_seconds"], **b["statistics"]})
        else:
            attempted = any(a["work_id"] == run_id for a in state["attempts"])
            record = {**row, "status": "failed" if attempted else "skipped", "reason": state.get("stop_reason", "not_yet_executed"),
                      "protector_seeds": None, "independent_mean": None}
            atomic_json(destination/"runs"/f"{run_id}.json", record)
        rows.append(record)
    aggregates = aggregate_dataset(rows)
    contrasts, pair_rows = [], []
    for scenario in plan["scenarios"]:
        for pop in (20, 40):
            differences, ses = [], []
            for repeat in range(3):
                a = next((r for r in results.values() if r["row"]["scenario_id"] == scenario["scenario_id"] and r["row"]["population_size"] == pop and r["row"]["repetition_index"] == repeat), None)
                b = next((r for r in results.values() if r["row"]["scenario_id"] == scenario["scenario_id"] and r["row"]["population_size"] == 10 and r["row"]["repetition_index"] == repeat), None)
                if a is None or b is None:
                    continue
                ca = [v for batch in a["final_batches"] for v in batch["rumor_counts"]]
                cb = [v for batch in b["final_batches"] for v in batch["rumor_counts"]]
                raw_diff = [x-y for x, y in zip(ca, cb)]
                delta = a["final"]["rumor_mean"]-b["final"]["rumor_mean"]
                mcse = stdev(raw_diff)/sqrt(len(raw_diff))
                differences.append(delta); ses.append(mcse)
                pair_rows.append({"dataset": scenario["dataset"], "scenario_id": scenario["scenario_id"], "population_size": pop,
                                  "repetition_index": repeat, "mean_difference": delta, "conditional_MC_SE_difference": mcse,
                                  "conditional_MC_paired_interval": paired_differences(ca, cb)})
            if len(differences) >= 2:
                contrasts.append({"dataset": scenario["dataset"], "scenario_id": scenario["scenario_id"], "rumor_seeds": scenario["rumor_seeds"],
                                  "population_size": pop, **contrast_summary(differences, ses, family_size=6)})
    counts = Counter(r["status"] for r in rows)
    selection = sum(r["selection_runtime_seconds"] for r in results.values())
    final = sum(r["final_evaluation_runtime_seconds"] for r in results.values())
    control_time = sum(r["runtime_seconds"] for r in controls.values())
    loading = sum(r["graph_loading_seconds"] for r in all_payloads)
    worker = sum(r["worker_runtime_seconds"] for r in all_payloads)
    attempts_time = sum(a["elapsed_seconds"] for a in state["attempts"])
    runtime = {"selection_optimization_seconds": selection, "fitness_MC_seconds_subset_of_selection": sum(r["fitness_evaluator_runtime_seconds"] for r in results.values()),
               "GA_final_evaluation_seconds": final, "shared_control_evaluation_seconds": control_time,
               "graph_loading_seconds": loading, "worker_other_seconds": worker-selection-final-control_time-loading,
               "process_startup_guard_and_output_seconds": attempts_time-worker,
               "parent_overhead_seconds": state.get("parent_overhead_seconds", 0), "total_active_experiment_seconds": state["active_runtime_seconds"],
               "scope": "active execution incl resource guard/imports/loading/exports; analysis/tests separate; paused idle time excluded"}
    actual_by_dataset = []
    for dataset in plan["protocol"]["datasets"]:
        group = [r for r in all_payloads if r["row"]["dataset"] == dataset]
        ga = [r for r in results.values() if r["row"]["dataset"] == dataset]
        actual_by_dataset.append({"dataset": dataset, "completed_GA_runs": len(ga), "evaluator_calls": sum(r["evaluator_calls"] for r in group),
                                  "CIC_simulations": sum(r["CIC_simulations"] for r in group),
                                  "selection_seconds": sum(r["selection_runtime_seconds"] for r in ga),
                                  "fitness_MC_seconds": sum(r["fitness_evaluator_runtime_seconds"] for r in ga),
                                  "final_evaluation_seconds": sum(r["final_evaluation_runtime_seconds"] for r in ga),
                                  "worker_peak_RSS_bytes": max((r["worker_peak_RSS_bytes"] for r in group), default=0),
                                  "cache_hits": sum(r["core_GA_result"]["cache_hit_count"] for r in ga)})
    summary = {"status": state.get("status", "incomplete"), "planned_GA_runs": 27, "completed_GA_runs": counts["completed"],
               "failed_GA_runs": counts["failed"], "skipped_GA_runs": counts["skipped"],
               "failed_or_interrupted_attempts": sum(a["status"] != "completed" for a in state["attempts"]),
               "optimization_evaluator_calls": sum(r["core_GA_result"]["evaluation_count"] for r in results.values()),
               "GA_final_evaluator_calls": sum(r["row"]["final_batches"] for r in results.values()), "control_evaluator_calls": len(controls),
               "total_actual_evaluator_calls": sum(r["evaluator_calls"] for r in all_payloads),
               "optimization_CIC_simulations": sum(r["core_GA_result"]["cic_simulation_count"] for r in results.values()),
               "GA_final_CIC_simulations": sum(r["row"]["S_eval"]*r["row"]["final_batches"] for r in results.values()),
               "control_CIC_simulations": sum(r["CIC_simulations"] for r in controls.values()),
               "total_actual_CIC_simulations": sum(r["CIC_simulations"] for r in all_payloads), "charged_CIC": state["charged_CIC"],
               "cache_hits": sum(r["core_GA_result"]["cache_hit_count"] for r in results.values()),
               "elite_fitness_reuses": sum(r["core_GA_result"]["elite_fitness_reuse_count"] for r in results.values()),
               "peak_worker_RSS_bytes": max((r["worker_peak_RSS_bytes"] for r in all_payloads), default=0),
               "runtime": runtime, "main_experiments_run": False, "cross_dataset_quality_pooling": False}
    decision = configuration_decision(summary, contrasts)
    proposal = {"status": "proposed_not_locked_or_executed", "decision": decision, "GA": plan["protocol"]["reference_ga"],
                "k": plan["protocol"]["k"], "p": plan["protocol"]["p"], "tie_breaking": plan["protocol"]["tie_breaking"],
                "S_opt": plan["protocol"]["S_opt"], "S_eval_per_batch": plan["protocol"]["S_eval_per_batch"], "final_batches": plan["protocol"]["final_batches"],
                "main_master_seed": plan["request"]["reserved_main_master_seed"], "reserved_scenarios": plan["main_reservations"],
                "independent_main_runs_confirmed": False, "main_run_slots_reserved_only": plan["request"]["reserved_main_run_slots"],
                "unconfirmed": ["main scenario/p grid and independent run count", "per-dataset main computational preflight", "practical equivalence/effect-size threshold", "precision and no-spread limitations on newly reserved R without exposing main outcomes to tuning"]}
    main_intervals = []
    for slot in plan["reserved_main_schedule"]:
        s_eval = plan["protocol"]["S_eval_per_batch"][slot["dataset"]]
        main_intervals.append({**slot, "S_opt": plan["protocol"]["S_opt"], "S_eval_per_batch": s_eval,
                               "final_batches": plan["protocol"]["final_batches"],
                               "optimization_seed_stop_exclusive": slot["optimization_base_random_seed"]+plan["protocol"]["S_opt"],
                               "final_batch_seeds": [slot["final_base_random_seed"]+b*s_eval for b in range(plan["protocol"]["final_batches"])],
                               "final_seed_stop_exclusive": slot["final_base_random_seed"]+s_eval*plan["protocol"]["final_batches"],
                               "block_stop_exclusive": slot["block_start"]+plan["protocol"]["random_seed_policy"]["block_width"]})
    usage = []
    for s in plan["old_scenarios"]:
        completed = sum(r["row"]["scenario_id"] == s["scenario_id"] for r in results.values())
        usage.append({**s, "Pilot2_NoIntervention_calibration": True,
                      "prior_GA_parameter_role": "development" if s["scenario_id"] in plan["protocol"]["development_scenario_ids"] else "held_out_from_GA_parameter_screening" if s["scenario_id"] in plan["protocol"]["validation_scenario_ids"] else "supplementary_not_a_main_blind_holdout",
                      "confirmation_GA_runs_completed": completed, "blind_for_official_main": False})
    for name, obj in (("run_results", rows), ("summary_by_dataset_configuration", aggregates), ("contrasts", contrasts),
                      ("paired_contrasts_by_repetition", pair_rows), ("control_results", control_rows), ("convergence", convergence),
                      ("final_batches", batch_rows), ("runtime_by_dataset", actual_by_dataset), ("scenario_usage", usage),
                      ("observed_artifact_audits", audits), ("reserved_main_seed_intervals", main_intervals)):
        atomic_json(destination/f"{name}.json", obj)
        write_csv(destination/f"{name}.csv", obj)
    atomic_json(destination/"configuration_decision.json", decision)
    atomic_json(destination/"main_configuration_proposal.json", proposal)
    summary["figures"] = create_figures(destination, aggregates, results) if figures and counts["completed"] == 27 else []
    summary["analysis_runtime_seconds"] = perf_counter()-started
    atomic_json(destination/"summary.json", summary)
    atomic_json(destination/"runtime.json", runtime)
    atomic_json(destination/"metadata.json", json.loads((root/"metadata.json").read_text()))
    atomic_json(destination/"integrity_after.json", json.loads((root/"integrity_after.json").read_text()))
    atomic_json(destination/"checkpoint_summary.json", {k: v for k, v in state.items() if k not in ("completed", "pending")})
    atomic_json(destination/"raw_artifact_inventory.json", {"directory": root.relative_to(PROJECT_ROOT).as_posix(),
                "files": {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}, "gitignored": True})
    return summary


def write_report(destination: Path, target: Path) -> None:
    """Render confirmed observations with per-dataset limits and no pooled winner."""
    load = lambda name: json.loads((destination/f"{name}.json").read_text())
    s, pre, config, summaries, contrasts = load("summary"), load("preflight"), load("config"), load("summary_by_dataset_configuration"), load("contrasts")
    rt, decision, reservations = s["runtime"], load("configuration_decision"), load("reserved_main_scenarios")
    verification = load("verification") if (destination/"verification.json").exists() else None
    sections = []
    for scenario in load("scenarios"):
        dataset = scenario["dataset"]
        rows = [r for r in summaries if r["dataset"] == dataset]
        table = "\n".join(f"| {r['population_size']} | {r['mean_training_fitness']:.3f} | {r['mean_over_GA_runs']:.3f} | {r['std_across_GA_run_means']:.3f} | [{r['CI95_over_GA_run_means_low']:.3f}, {r['CI95_over_GA_run_means_high']:.3f}] | {r['mean_conditional_MC_SE']:.3f} | {r['mean_selection_seconds']:.2f} | {r['mean_final_evaluation_seconds']:.2f} | {r['mean_optimization_evaluator_calls']:.1f} | {r['mean_cache_hits']:.1f} |" for r in rows)
        ctable = "\n".join(f"| {c['population_size']} | {c['mean_difference']:+.3f} | [{c['pointwise_CI95_low']:+.3f}, {c['pointwise_CI95_high']:+.3f}] | [{c['Bonferroni_family_CI95_low']:+.3f}, {c['Bonferroni_family_CI95_high']:+.3f}] | {c['conclusion']} |" for c in contrasts if c["dataset"] == dataset)
        by_pop = {r["population_size"]: r for r in rows}
        if dataset == "email-Eu-core":
            interpretation = "Training fitness gần floor1 trong cả ba cấu hình; final means không bằng training fitness. Source có 96% no-growth trong Pilot2, nên panel này kiểm tra được khả năng chạy trên R mới nhưng yếu để phân biệt population. Mean N40 lớn hơn N10 trong sample này không đủ chứng minh N40 kém hơn."
        elif dataset == "ego-Facebook":
            ratio = by_pop[40]["mean_selection_seconds"]/by_pop[10]["mean_selection_seconds"]
            interpretation = f"Mean final giảm mô tả khi tăng N, nhưng hai contrast CIs còn chứa0. N40 tốn {ratio:.2f} lần selection time của N10. Training–final gaps vẫn lớn và tăng search effort không tự chứng minh lợi ích đủ chắc chắn để thay reference."
        else:
            negative = [r["population_size"] for r in rows if r["GA_variance_component_untruncated"] < 0]
            interpretation = f"Final means còn gần nhau trong khi conditional MC SE đáng kể. Raw GA variance component âm ở N={negative}; giữ nguyên giá trị âm thay vì xem nó là bằng chứng GA ổn định tuyệt đối. CI qua chỉ ba run means có thể hẹp do ngẫu nhiên, không thay thế MC diagnostics hoặc chứng minh equivalence."
        sections.append(f"""### {dataset}, R={scenario['rumor_seeds']}

Reachable={scenario['reachable_count']}, stratum={scenario['stratum']}. Mỗi N
có đúng 3 independent GA runs; không dùng các MC observations như GA repeats.

| N | Training mean | Final mean | SD giữa GA means | CI95 qua GA runs | Mean conditional MC SE | Selection s/run | Final s/run | Fitness calls/run | Cache hits/run |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
{table}

Delta=alternative−reference, số âm là ít rumor hơn; chỉ so trong scenario này.

| N | Delta | Pointwise CI95 (3 pairs) | Family CI95 (Bonferroni, 6 contrasts) | Diễn giải |
|---|---:|---|---|---|
{ctable}

{interpretation}

![Quality/cost {dataset}](docs/cross_scenario_ga_confirmation/figures/{dataset}_quality_cost.png)

![Convergence {dataset}](docs/cross_scenario_ga_confirmation/figures/{dataset}_convergence.png)
""")
    holdouttable = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {r['stratum']} | {r['reachable_count']} | {r['sampling_seed']} | 0 |" for r in reservations)
    runtime_table = "\n".join(f"| {r['dataset']} | {r['completed_GA_runs']} | {r['evaluator_calls']} | {r['CIC_simulations']} | {r['selection_seconds']:.3f} | {r['final_evaluation_seconds']:.3f} | {r['worker_peak_RSS_bytes']/1024**2:.1f} |" for r in load("runtime_by_dataset"))
    test_text = f"**{verification['tests_passed']}/{verification['tests_run']} tests pass**; {verification['protected_files_checked']} existing protected files, trong đó {verification['data_files_checked']} data files, giữ nguyên checksum." if verification else "Final tests/checksum verification đang chờ cập nhật verification.json."
    target.write_text(f"""# Cross-Scenario GA Configuration Confirmation

**{s['completed_GA_runs']}/27 GA runs thành công**, {s['failed_GA_runs']} failed,
{s['skipped_GA_runs']} skipped; {s['failed_or_interrupted_attempts']} failed/interrupted attempts.
Đây là kiểm tra ứng dụng của ba cấu hình đã định trước, không mở rộng parameter
search, không chạy Main Experiments và không chọn rumor seeds theo score thuật toán.

## 1. Thiết kế cố định trước execution

Reference đọc nguyên `reference_ga` của Protocol v1: N10/G10, crossover0.8,
mutation0.1, tournament3, elitism1, cache=True. Hai alternatives chỉ đổi N20/N40.
3 datasets ×3 profiles ×3 independent repetitions=27 GA runs; 9 runs/dataset.
Giữ k=5, p=.03, protector-priority và S_opt=100. Email dùng S_eval=6.000/batch,
Facebook/Wiki 2.500/batch, **B=2**; pooled final S=12.000/5.000 mỗi P.

Mọi cấu hình giữ cùng graph/R/k/p/tie/S trong scenario, không thay profile sau
khi xem kết quả. Order N được counterbalance theo repetition. Giữ API/semantics
IC/CIC/MC/GA/baseline; dùng lại chính V2 worker và `evaluate_cic()` cũ. Khóa P
của mỗi run trước independent final evaluation; kết quả final không quay về GA.
Cache/elite giữ nguyên chính sách fixed fitness schedule, cache cục bộ mỗi call.

## 2. Scenarios và phân chia dữ liệu

Chọn nguyên algorithm-outcome-validation scenarios của Protocol v1, được lấy
mẫu đều actual IDs trong reachability strata Pilot 2. Việc chọn không dùng
GA/baseline quality, không thay R vì control nhỏ. Reachable gồm source và tuân
theo hướng cạnh.
Ở đây "đại diện" là một source trong topology stratum đã lấy mẫu trước,
không phải khẳng định nó đại diện phân bố stochastic spread của cả dataset.

| Dataset | R confirmation | Reachable | Stratum | Prior Pilot2 p=.03 No Intervention mean/S200 | Prior no-growth fraction |
|---|---|---:|---|---:|---:|
| email-Eu-core | [858] | 966 | high | 5.560 | 96.0% |
| ego-Facebook | [1555] | 4.039 | constant | 175.555 | 36.5% |
| Wiki-Vote | [2110] | 2.317 | high | 5.015 | 89.5% |

Đây là các R đã có No Intervention scan trong calibration, nhưng chưa dùng
GA outcomes cho Pilot2/v1/V2 parameter screening. Confirmation hiện tại tiêu
thụ chúng cho đánh giá cấu hình: **không tiếp tục gọi chúng là blind holdouts
cho main**. Không ghi đè vai trò lịch sử trong frozen Protocol-v1 JSON.

Development R926/1180/1210 đã dùng trong algorithm calibration trước đây;
R926 còn dùng cho Reduced Screen V2. R858 và R2110 có potential reachability
cao nhưng stochastic spread nhỏ tại p=.03. Điều này gây floor/no-growth và
hạn chế khả năng phân biệt N; không diễn giải việc CI rộng thành equivalence.
R1555 cùng connected graph Facebook nhưng kết quả vẫn chỉ đại diện một source.
Low/legacy scenarios vẫn được giữ trong manifest, không tự loại khỏi kế hoạch
phân tích bổ sung. `scenario_usage.csv/json` ghi usage/confirmation counts.
Protocol Validation trước Pilot2 còn dùng email R577/Facebook R2162/Wiki
R4341; reserved main R mới cũng được audit không trùng các R này hoặc email
R0 của các smoke cũ (`main_holdout_prior_usage_audit.json`).

## 3. Seed policy và bảo vệ Main Experiments

Confirmation master={config['master_seed']}, khác V2=2026111110, pilot v1=2026111107
và reserved main={config['reserved_main_master_seed']}. Width=1.000.000, dùng
Cantor block/phase SHA256 của runner hiện có. Mỗi profile/repetition có opt index
=(scenario_index+1)*10000+profile_ordinal*100+repeat, cho 27 optimizer/fitness
schedules riêng. Fitness là base+i với i=0..99 trong từng GA, không đổi theo gen.
Final index=scenario_index*100+repeat, nửa final của block; batch b bắt đầu
final_base+b*S_eval. Cùng final seeds giữa N trong một scenario/repetition,
khác repetitions và không giao bất cứ opt interval nào. Cùng seed labels không
bảo đảm identical random edge outcomes khi valid attempts thay đổi theo P.

Reserved main R được lấy mẫu **topology-only**, uniform trong high/constant
theo rule Pilot 2, loại mọi R trong frozen manifest. Không đọc score GA/control
để chọn các R này và chưa chạy No Intervention hoặc thuật toán trên chúng.

| Dataset | R đề xuất giữ riêng | Stratum | Reachable | Sampling seed | Diffusion observations |
|---|---|---|---:|---:|---:|
{holdouttable}

Sampling master={config['main_holdout_sampling_master_seed']}. Các R mới có ordinal
11..16 trong derived reservation, không sửa frozen manifest gốc. Giữ main master
2026111109, preallocate 10 slots/scenario (`index=scenario_index*100+repeat`),
tổng60 **reserved slots, không phải 60 main runs đã được chốt/chạy**. Main repeats
còn cần xác nhận. Các block labels trong reserved_main_schedule.json/csv;
explicit opt/final intervals và hai batch bases trong reserved_main_seed_intervals.json/csv;
reserved_main_scenarios.json ghi rule/excluded IDs/reachable. V2/confirmation
observations không là bằng chứng cuối cùng cho main. Giữ primary/supplementary
role thay vì xem high-stratum sample như uniform toàn bộ V.

## 4. Computational preflight và chi phí thực đo

Bound calls/run U=N+G(N−E): 100/210/430 ứng với N10/20/40. Mỗi dataset có
3×(100+210+430)=2.220 fitness calls, S_opt100. Shared No Intervention một lần
cho scenario/repeat/batch, không lặp cho từng N.

| Phase | Evaluator calls upper | CIC simulations upper |
|---|---:|---:|
| Fitness | 6.660 | 666.000 |
| Independent GA final | 54 | 198.000 |
| Shared control | 18 | 66.000 |
| Tổng | 6.732 | 930.000 |

Pilot2 rate projection trước safety={pre['rate_projection_seconds_before_safety']:.3f} s;
nhân safety1.5={pre['rate_projection_seconds_with_safety']:.3f} s; cộng loading/
setup/export allowance300 s thành **{pre['projected_seconds_including_overhead']:.3f} s**,
dưới cap10.800 s. Counts dưới cap120GA/3.000.000CIC. Đây là **ngoại suy từ R
khác**, không phải measured runtime hoặc hard upper bound. R mới/P khác có
thể đổi tốc độ; engine dừng nếu cumulative time/CIC vượt cap, không tự giảm S.

Memory probes chỉ load graph+deepcopy, 0 diffusion calls. Projected RSS=
2×max probe+256MiB={pre['memory']['projected_worker_RSS_bytes']/1024**2:.1f} MiB.
Giới hạn worker={pre['memory']['worker_RSS_limit_bytes']/1024**3:.1f} GiB, concurrency=1;
peak worker đo thực={s['peak_worker_RSS_bytes']/1024**2:.1f} MiB. Watchdog dùng
resource.ru_maxrss/heartbeat bên trong worker, parent đọc heartbeat và timeout;
không cần quyền process listing. Sampling interval0.5s không là instantaneous
hard memory ceiling; short spikes vẫn được ghi trong peak RSS, phát hiện ở
lần check tiếp theo. Giới hạn là RSS, không phải virtual address space.

**Actual {s['total_actual_evaluator_calls']} evaluator calls, {s['total_actual_CIC_simulations']:,} CIC**:
fitness={s['optimization_evaluator_calls']} calls/{s['optimization_CIC_simulations']:,} CIC;
final={s['GA_final_evaluator_calls']} calls/{s['GA_final_CIC_simulations']:,} CIC;
control={s['control_evaluator_calls']} calls/{s['control_CIC_simulations']:,} CIC.
Cache hits={s['cache_hits']}; elite carries={s['elite_fitness_reuses']}.

| Dataset | GA runs | Total calls | Total CIC | Selection s | GA final s | Peak worker MiB |
|---|---:|---:|---:|---:|---:|---:|
{runtime_table}

Tổng active execution={rt['total_active_experiment_seconds']:.3f} s: selection
{rt['selection_optimization_seconds']:.3f} s (fitness MC
{rt['fitness_MC_seconds_subset_of_selection']:.3f} s **đã nằm trong selection**),
GA final {rt['GA_final_evaluation_seconds']:.3f} s, control
{rt['shared_control_evaluation_seconds']:.3f} s, loading
{rt['graph_loading_seconds']:.3f} s; còn lại imports/guard/JSON/bookkeeping.
Analysis/plot/tests tách khỏi algorithm runtime. Checkpoint atomic từng unit,
resume xác minh fingerprint/hashes rồi bỏ qua units đã lưu; cumulative caps
không reset. Unknown partial work bị charge upper CIC/timeout thay vì ghi0.

## 5. Kết quả theo từng dataset

SD/CI qua GA runs bao gồm biến động GA và MC error. Conditional MC SE/CI của
P cố định được lưu từng batch và pooled; không nhầm std CIC với SE của mean.
Training–final gaps ghi riêng; không chọn cấu hình bằng training fitness.
Các CI t(df=2) qua ba runs có độ bất định rất lớn, nhất là rare large cascades.

{''.join(sections)}
## 6. Diễn giải bất định và quyết định cấu hình

Decision machine-readable: **{decision['decision']}**;
{decision['family_CI_resolved_contrasts']}/6 contrasts có family CI loại0.
Chỉ so N20−N10 và N40−N10 trong cùng scenario. Pointwise95% và approximate
Bonferroni family95% cho sáu planned contrasts đều được lưu. Correction không
gộp effect sizes/rumor counts giữa datasets. **CI chứa0 nghĩa là chưa đủ bằng
chứng khác biệt, không chứng minh tương đương**; chưa có equivalence margin,
power analysis hoặc global optimum claim.

Variance-components giữ Var(run means), mean(MC SE²), raw difference kể cả
âm; display clipped>=0 riêng. Với contrasts, MC SE dùng seed-aligned raw
differences. n=3 không cho phép decomposition ổn định hoặc chứng minh cấu
hình tổng quát. Các training curves là diagnostic, không là final quality.

Đề xuất cấu hình cần khóa nếu người dùng xác nhận protocol main: **reference
N10/G10/crossover0.8/mutation0.1/tournament3/elitism1/cache=True**, giữ
k5/p.03/protector-priority/S_opt100 và S_eval/B v1. Khi decision yêu cầu review,
chưa nên khóa main trước khi xem các contrasts và giới hạn tương ứng. Giữ
reference là lựa chọn đã định trước có chi phí thấp, không phải tuyên bố nó
vượt alternatives hay tương đương chúng. Không tự cập nhật frozen v1 hoặc
chọn N20/N40 chỉ từ một scenario; không tiếp tục search tham số trong stage này.

Khả năng khái quát còn giới hạn: một R mỗi graph; only high/constant strata;
email/Wiki control ít spread; ba GA repeats; fixed S_opt100 fitness noise và
selection bias; p/k cố định; N tăng đồng thời tăng search/evaluation effort.
Các R main mới chưa có outcome nên chưa biết mức spread/precision; cần chốt
main protocol và preflight riêng, không xem kết quả main rồi quay lại tuning.
`main_configuration_proposal.json` là proposal, main repeats và scenario/p
grid chưa tự chốt chỉ vì đã reserve seed slots.

## 7. Kiểm chứng và artifacts

{test_text}
Raw/processed topology, IC/CIC/Monte Carlo/GA/Greedy/baseline và frozen v1 không
đổi. Prior Pilot2/v1/V2 artifacts được kiểm tra độc lập. Mọi thống kê final,
population invariants/elite carries/counters được audit lại từ checkpoint.
Không chạy Main Experiments/Full Design. Không tái sử dụng observations hiện
tại làm official main evidence.

[matrix.csv](docs/cross_scenario_ga_confirmation/matrix.csv),
[run_results.csv](docs/cross_scenario_ga_confirmation/run_results.csv),
[summary_by_dataset_configuration.csv](docs/cross_scenario_ga_confirmation/summary_by_dataset_configuration.csv),
[contrasts.csv](docs/cross_scenario_ga_confirmation/contrasts.csv),
[convergence.csv](docs/cross_scenario_ga_confirmation/convergence.csv),
[main_configuration_proposal.json](docs/cross_scenario_ga_confirmation/main_configuration_proposal.json).
Per-run JSON/history ở docs/cross_scenario_ga_confirmation/runs; raw counts/
complete GA payloads/checkpoints ở results/cross_scenario_ga_confirmation
(gitignored), có raw inventory/hashes và metadata Python/libs/OS/hardware/Git.

```sh
.venv/bin/python -B -m experiments.cross_scenario_ga_confirmation --phase preflight
.venv/bin/python -B -u -m experiments.cross_scenario_ga_confirmation --phase run
.venv/bin/python -B -m experiments.analyze_cross_scenario_confirmation
.venv/bin/python -B -m unittest discover -s tests -q
```
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT/"results/cross_scenario_ga_confirmation")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT/"docs/cross_scenario_ga_confirmation")
    args = parser.parse_args(argv)
    summary = analyze(args.root, args.output)
    if summary["completed_GA_runs"] == 27:
        write_report(args.output, PROJECT_ROOT/"CROSS_SCENARIO_GA_CONFIRMATION.md")
    print(json.dumps({k: v for k, v in summary.items() if k != "figures"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
