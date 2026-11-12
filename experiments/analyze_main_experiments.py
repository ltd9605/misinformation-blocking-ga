"""Audit and analyze the frozen four-run main matrix without further simulations."""

import argparse
from collections import Counter
import json
from math import sqrt
import os
from pathlib import Path
from statistics import mean, stdev
from tempfile import gettempdir
from time import perf_counter

os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir())/"misinformation-main-matplotlib"))

from experiments.main_statistics import average_reduction_sets, fieller_reduction, paired_effect, reduction_point, run_summary
from experiments.pilot_protocol_validation import write_csv
from experiments.reduced_screen_v2 import atomic_json
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.calibration import jaccard, observation_summary


METHODS = ("no_intervention", "random", "degree", "pagerank", "candidate_restricted_greedy", "genetic_algorithm")
DETERMINISTIC = {"no_intervention", "degree", "pagerank"}


def read_completed(root: Path) -> tuple[dict, dict, dict, dict, list[dict]]:
    """Verify immutable worker hashes before trusting any numeric observation."""
    plan = json.loads((root/"frozen_plan.json").read_text())
    state = json.loads((root/"checkpoint.json").read_text())
    selections, batches, payloads = {}, {}, []
    expected = {r["unit_id"]: r for r in plan["matrix"] if r["method_eligible"]}
    for work_id, path in state["completed"].items():
        if sha256_file(Path(path)) != state["result_sha256"][work_id]:
            raise ValueError("Main result checksum changed")
        payload = json.loads(Path(path).read_text())
        row = payload["row"]
        if row != expected[row["unit_id"]] or not payload["graph_unchanged"]:
            raise ValueError("Main observation differs from frozen context")
        payloads.append(payload)
        if payload["kind"] == "selection":
            selections[row["unit_id"]] = payload
        else:
            batches[(row["unit_id"], payload["batch"])] = payload
    return plan, state, selections, batches, payloads


def audit_records(plan: dict, state: dict, selections: dict, batches: dict) -> dict:
    """Validate feasibility, seeds, graph immutability, elites, work counts and all raw MC counts."""
    graph_sizes = {g["dataset"]: (g["nodes"], g["edges"]) for g in plan["graphs"]}
    generation_rows = individuals = elites = raw_observations = 0
    def require(value, message):
        if not value:
            raise ValueError(f"Main artifact audit: {message}")
    for unit_id, selection in selections.items():
        row = selection["row"]
        nodes, edges = graph_sizes[row["dataset"]]
        require((selection["graph_nodes"], selection["graph_edges"]) == (nodes, edges), "selection topology")
        P, R = set(selection["protector_seeds"]), set(row["rumor_seeds"])
        require(len(P) == len(selection["protector_seeds"]) == (0 if row["algorithm"] == "no_intervention" else row["k"]), "P size")
        require(not P&R, "P/R disjoint")
        timing, detail = selection["timing"], selection["selection_details"]
        require(selection["CIC_simulations"] == timing["optimization_evaluation_count"]*row["S_opt"], "optimization CIC")
        require(selection["CIC_simulations"] <= row["budgeted_optimization_CIC_upper"], "optimization work bound")
        if row["algorithm"] == "genetic_algorithm":
            require(len(detail["history"]) == row["max_generations"]+1, "GA stopping")
            require(len(detail["fitness_evaluations"]) == detail["evaluation_count"] == selection["evaluator_calls"], "GA actual evaluator calls")
            require(detail["seeds"]["fitness_base_random_seed"] == row["optimization_base_random_seed"], "GA fitness seed")
            require(detail["seeds"]["operators_seed"] == row["GA_operators_seed"], "GA operators seed")
            require(detail["best_protector_nodes"] == selection["protector_seeds"], "GA best P")
            require(detail["best_estimated_fitness"] == timing["optimization_best_estimated_fitness"], "GA training fitness diagnostic")
            eligible = set(detail["eligible_nodes"])
            previous = None
            for generation, h in enumerate(detail["history"]):
                generation_rows += 1
                require(h["generation"] == generation and len(h["population"]) == row["population_size"], "GA population size")
                for p in h["population"]:
                    individuals += 1
                    require(len(p) == len(set(p)) == row["k"] and not set(p)&R and set(p) <= eligible, "GA individual")
                if previous:
                    ranked = sorted(zip(previous["fitness_values"], previous["population"]), key=lambda pair: (pair[0], pair[1]))
                    required = Counter((f, tuple(p)) for f, p in ranked[:row["elitism_count"]])
                    carried = Counter((f, tuple(p)) for f, p in zip(h["fitness_values"], h["population"]))
                    require(all(carried[k] >= v for k, v in required.items()), "GA elite preservation")
                    elites += row["elitism_count"]
                previous = h
        elif row["algorithm"] == "candidate_restricted_greedy":
            require(detail["evaluation_count"] == selection["evaluator_calls"] == 40, "Restricted Greedy calls")
            require(len(detail["candidate_nodes"]) == 10 and not set(detail["candidate_nodes"])&R, "Restricted pool")
            require(detail["protector_nodes"] == selection["protector_seeds"], "Restricted best P")
            require(len(detail["steps"]) == row["k"] and sum(len(s["candidate_evaluations"]) for s in detail["steps"]) == 40, "Restricted steps")
        else:
            require(selection["evaluator_calls"] == selection["CIC_simulations"] == 0, "baseline selection has no fitness MC")
    for (unit_id, batch), result in batches.items():
        row = result["row"]
        require(unit_id in selections, "final before selection")
        require(result["protector_seeds"] == selections[unit_id]["protector_seeds"], "final uses sealed P")
        require(result["selection_sha256"] == state["result_sha256"][f"select_{unit_id}"], "final selection hash")
        require(result["base_random_seed"] == row["final_batch_seeds"][batch], "final batch seed")
        require(result["evaluator_calls"] == 1 and result["CIC_simulations"] == row["S_eval_per_batch"], "final work count")
        counts = result["raw_counts"]
        require(all(len(v) == row["S_eval_per_batch"] for v in counts.values()), "raw array lengths")
        nodes, edges = graph_sizes[row["dataset"]]
        require((result["graph_nodes"], result["graph_edges"]) == (nodes, edges), "final topology")
        for r, p, inactive, steps in zip(counts["rumor_count"], counts["protector_count"], counts["inactive_count"], counts["steps"]):
            require(r >= len(row["rumor_seeds"]) and p >= len(result["protector_seeds"]) and inactive >= 0 and steps >= 0 and r+p+inactive == nodes, "raw count conservation")
            if row["algorithm"] == "no_intervention":
                require(p == 0, "NI has no protector nodes")
            raw_observations += 1
        require(result["statistics"] == observation_summary(counts["rumor_count"], nodes), "batch statistics recomputed")
        require(result["mean_protector_count"] == mean(counts["protector_count"]) and result["mean_inactive_count"] == mean(counts["inactive_count"]), "other cascade means")
    for scenario in plan["scenarios"]:
        for method in DETERMINISTIC:
            group = [s for s in selections.values() if s["row"]["scenario_id"] == scenario["scenario_id"] and s["row"]["algorithm"] == method]
            require(len({tuple(s["protector_seeds"]) for s in group}) <= 1, "deterministic method P changed between runs")
    return {"passed": True, "selections_checked": len(selections), "final_batches_checked": len(batches),
            "raw_final_CIC_observations_recomputed": raw_observations, "GA_convergence_rows": generation_rows,
            "GA_individuals_checked": individuals, "GA_elite_carries_checked": elites,
            "optimization_raw_CIC_observations_retained": False, "official_resimulations_for_audit": 0}


def primary_rows(plan: dict, state: dict, selections: dict, batches: dict) -> tuple[list[dict], dict]:
    """Exactly144 result rows; Full Greedy status is exported separately."""
    sizes = {g["dataset"]: g["nodes"] for g in plan["graphs"]}
    rows, counts_by_unit = [], {}
    for row in [r for r in plan["matrix"] if r["method_eligible"]]:
        unit = row["unit_id"]
        selection = selections.get(unit)
        final = [batches.get((unit, b)) for b in range(row["final_batches"])]
        work_ids = {f"select_{unit}", *(f"final_{unit}_b{b}" for b in range(row["final_batches"]))}
        attempts = [a for a in state["attempts"] if a["work_id"] in work_ids]
        if selection is None or not all(final):
            failed = any(a["status"] != "completed" for a in attempts)
            available = [b for b in final if b is not None]
            known_calls = (selection["evaluator_calls"] if selection else 0)+len(available)
            known_CIC = (selection["CIC_simulations"] if selection else 0)+sum(b["CIC_simulations"] for b in available)
            rows.append({**row, "status": "failed" if failed else "skipped", "execution_status": "incomplete",
                         "reason": state.get("stop_reason", "not_yet_executed"),
                         "protector_seeds": selection["protector_seeds"] if selection else None, "rumor_mean": None,
                         "actual_evaluator_calls": known_calls, "actual_CIC_simulations": known_CIC,
                         "actual_work_is_lower_bound_if_unknown_partial_attempt": failed,
                         "selection_runtime_seconds": selection["timing"]["selection_runtime_seconds"] if selection else None,
                         "final_evaluation_runtime_seconds": sum(b["final_evaluation_runtime_seconds"] for b in available) if available else None,
                         "total_runtime_seconds": sum(a["elapsed_seconds"] for a in attempts) if attempts else None})
            continue
        counts = [v for b in final for v in b["raw_counts"]["rumor_count"]]
        counts_by_unit[unit] = counts
        statistics = observation_summary(counts, sizes[row["dataset"]])
        timing, detail = selection["timing"], selection["selection_details"]
        rows.append({**row, "status": "completed", "execution_status": "completed", "reason": None, "protector_seeds": selection["protector_seeds"],
                     "measured_rumor_mean": statistics["rumor_mean"], "measured_runtime_seconds": sum(a["elapsed_seconds"] for a in attempts),
                     "actual_evaluator_calls": selection["evaluator_calls"]+len(final),
                     "actual_CIC_simulations": selection["CIC_simulations"]+sum(b["CIC_simulations"] for b in final),
                     "rumor_mean": statistics["rumor_mean"], "rumor_SD_population": statistics["rumor_std_population"],
                     "rumor_SD_sample": statistics["rumor_std_sample"], "rumor_MC_SE": statistics["rumor_SE"],
                     "rumor_MC_CI95_low": statistics["ci95_low"], "rumor_MC_CI95_high": statistics["ci95_high"],
                     "final_simulations": statistics["S"], "min_rumor_count": statistics["min_rumor_count"],
                     "max_rumor_count": statistics["max_rumor_count"], "rumor_fraction": statistics["rumor_fraction"],
                     "no_growth_fraction": statistics["no_spread_fraction"],
                     "mean_protector_count": mean(v for b in final for v in b["raw_counts"]["protector_count"]),
                     "mean_inactive_count": mean(v for b in final for v in b["raw_counts"]["inactive_count"]),
                     "training_fitness_diagnostic": timing["optimization_best_estimated_fitness"],
                     "independent_minus_training": statistics["rumor_mean"]-timing["optimization_best_estimated_fitness"] if timing["optimization_best_estimated_fitness"] is not None else None,
                     "selection_runtime_seconds": timing["selection_runtime_seconds"],
                     "fitness_MC_seconds_subset_of_selection": timing["optimization_evaluator_seconds"],
                     "candidate_pool_selection_seconds": timing["candidate_pool_selection_seconds"],
                     "final_evaluation_runtime_seconds": sum(b["final_evaluation_runtime_seconds"] for b in final),
                     "total_runtime_seconds": sum(a["elapsed_seconds"] for a in attempts),
                     "graph_loading_seconds": selection["graph_loading_seconds"]+sum(b["graph_loading_seconds"] for b in final),
                     "optimization_evaluator_calls": selection["evaluator_calls"], "final_evaluator_calls": len(final),
                     "total_evaluator_calls": selection["evaluator_calls"]+len(final),
                     "optimization_CIC_simulations": selection["CIC_simulations"],
                     "final_CIC_simulations": sum(b["CIC_simulations"] for b in final),
                     "CIC_simulations": selection["CIC_simulations"]+sum(b["CIC_simulations"] for b in final),
                     "cache_hits": detail.get("cache_hit_count"), "elite_fitness_reuses": detail.get("elite_fitness_reuse_count"),
                     "worker_peak_RSS_bytes": max([selection["worker_peak_RSS_bytes"]]+[b["worker_peak_RSS_bytes"] for b in final])})
    controls = {(r["scenario_id"], r["repetition_index"]): r for r in rows if r["status"] == "completed" and r["algorithm"] == "no_intervention"}
    for row in rows:
        if row["status"] != "completed":
            continue
        control = controls.get((row["scenario_id"], row["repetition_index"]))
        row["control_rumor_mean"] = control["rumor_mean"] if control else None
        row["absolute_rumor_reduction"] = control["rumor_mean"]-row["rumor_mean"] if control else None
        row["spread_reduction_fraction"] = 1-row["rumor_mean"]/control["rumor_mean"] if control and control["rumor_mean"] else None
        row["spread_reduction_percent"] = 100*row["spread_reduction_fraction"] if row["spread_reduction_fraction"] is not None else None
    return rows, counts_by_unit


def scenario_summaries(plan: dict, rows: list[dict]) -> list[dict]:
    """Within each fixed R, describe four runs and conditional MC uncertainty."""
    summaries = []
    for scenario in plan["scenarios"]:
        for method in METHODS:
            group = sorted([r for r in rows if r["scenario_id"] == scenario["scenario_id"] and r["algorithm"] == method and r["status"] == "completed"], key=lambda r: r["repetition_index"])
            if len(group) != 4:
                summaries.append({"dataset": scenario["dataset"], "scenario_id": scenario["scenario_id"], "rumor_seeds": scenario["rumor_seeds"],
                                  "algorithm": method, "status": "incomplete_no_primary_inference", "completed_runs": len(group)})
                continue
            control = sorted([r for r in rows if r["scenario_id"] == scenario["scenario_id"] and r["algorithm"] == "no_intervention" and r["status"] == "completed"], key=lambda r: r["repetition_index"])
            if len(control) != 4:
                continue
            values, controls = [r["rumor_mean"] for r in group], [r["rumor_mean"] for r in control]
            reduction = {"kind": "structural_zero_control", "intervals": [[0, 0]], "point_estimate": 0, "descriptive_only": True} if method == "no_intervention" else fieller_reduction(values, controls)
            summaries.append({"dataset": scenario["dataset"], "scenario_id": scenario["scenario_id"], "rumor_seeds": scenario["rumor_seeds"],
                              "algorithm": method, "status": "completed", **run_summary(values, [r["rumor_MC_SE"] for r in group], deterministic=method in DETERMINISTIC),
                              "No_Intervention_mean": mean(controls), "absolute_rumor_reduction": mean(controls)-mean(values),
                              "spread_reduction_fraction": reduction_point(values, controls),
                              "spread_reduction_percent": 100*reduction_point(values, controls), "spread_reduction_descriptive_CI": reduction,
                              "mean_no_growth_fraction": mean(r["no_growth_fraction"] for r in group),
                              "mean_selection_runtime_seconds": mean(r["selection_runtime_seconds"] for r in group),
                              "mean_final_evaluation_runtime_seconds": mean(r["final_evaluation_runtime_seconds"] for r in group),
                              "mean_total_runtime_seconds": mean(r["total_runtime_seconds"] for r in group),
                              "total_evaluator_calls": sum(r["total_evaluator_calls"] for r in group),
                              "total_CIC_simulations": sum(r["CIC_simulations"] for r in group),
                              "mean_cache_hits": mean(r["cache_hits"] for r in group) if method == "genetic_algorithm" else None,
                              "mean_training_fitness_diagnostic": mean(r["training_fitness_diagnostic"] for r in group) if method in ("genetic_algorithm", "candidate_restricted_greedy") else None,
                              "mean_independent_minus_training": mean(r["independent_minus_training"] for r in group) if method in ("genetic_algorithm", "candidate_restricted_greedy") else None,
                              "unique_protector_sets": len({tuple(r["protector_seeds"]) for r in group}),
                              "mean_pairwise_P_Jaccard": mean(jaccard(a["protector_seeds"], b["protector_seeds"]) for i, a in enumerate(group) for b in group[i+1:])})
    return summaries


def dataset_summaries(plan: dict, rows: list[dict], scenario_summary: list[dict]) -> list[dict]:
    """Equal two-scenario bundles per repeat; no cross-dataset quality pooling."""
    lookup = {(r["scenario_id"], r["algorithm"], r["repetition_index"]): r for r in rows if r["status"] == "completed"}
    result = []
    for dataset in plan["base_protocol"]["datasets"]:
        scenarios = [s["scenario_id"] for s in plan["scenarios"] if s["dataset"] == dataset]
        for method in METHODS:
            if any((s, method, rep) not in lookup or (s, "no_intervention", rep) not in lookup for s in scenarios for rep in range(4)):
                continue
            values, ses, controls = [], [], []
            for rep in range(4):
                values.append(mean(lookup[(s, method, rep)]["rumor_mean"] for s in scenarios))
                controls.append(mean(lookup[(s, "no_intervention", rep)]["rumor_mean"] for s in scenarios))
                ses.append(sqrt(sum(lookup[(s, method, rep)]["rumor_MC_SE"]**2 for s in scenarios))/2)
            parts = [next(r for r in scenario_summary if r["scenario_id"] == s and r["algorithm"] == method) for s in scenarios]
            reductions = []
            for s in scenarios:
                reductions.append(fieller_reduction([lookup[(s, method, r)]["rumor_mean"] for r in range(4)],
                                                    [lookup[(s, "no_intervention", r)]["rumor_mean"] for r in range(4)], alpha=.025))
            ratio_CI = average_reduction_sets(*reductions)
            if method == "no_intervention":
                ratio_CI = {"kind": "structural_zero_control", "intervals": [[0, 0]], "descriptive_only": True}
            result.append({"dataset": dataset, "algorithm": method, "fixed_scenarios": scenarios, "scenario_weights": [.5, .5],
                           "scenario_population_inference": False, "status": "completed",
                           **run_summary(values, ses, deterministic=method in DETERMINISTIC),
                           "No_Intervention_mean": mean(controls), "absolute_rumor_reduction_equal_scenario_weight": mean(controls)-mean(values),
                           "spread_reduction_fraction": mean(r["spread_reduction_fraction"] for r in parts),
                           "spread_reduction_percent": 100*mean(r["spread_reduction_fraction"] for r in parts),
                           "spread_reduction_descriptive_CI": ratio_CI,
                           "scenario_mean_min": min(r["mean_rumor"] for r in parts), "scenario_mean_max": max(r["mean_rumor"] for r in parts),
                           "scenario_mean_range_descriptive": max(r["mean_rumor"] for r in parts)-min(r["mean_rumor"] for r in parts),
                           "mean_selection_runtime_seconds": mean(r["mean_selection_runtime_seconds"] for r in parts),
                           "mean_final_evaluation_runtime_seconds": mean(r["mean_final_evaluation_runtime_seconds"] for r in parts),
                           "mean_total_runtime_seconds": mean(r["mean_total_runtime_seconds"] for r in parts),
                           "total_evaluator_calls": sum(r["total_evaluator_calls"] for r in parts),
                           "total_CIC_simulations": sum(r["total_CIC_simulations"] for r in parts)})
    return result


def method_comparisons(plan: dict, rows: list[dict], counts: dict) -> list[dict]:
    """Exactly30 scenario and15 dataset effects in the frozen family45."""
    lookup = {(r["scenario_id"], r["algorithm"], r["repetition_index"]): r for r in rows if r["status"] == "completed"}
    effects, conditional_by_scenario = [], {}
    for scenario in plan["scenarios"]:
        s = scenario["scenario_id"]
        for comparator in plan["request"]["analysis_policy"]["comparators"]:
            if any((s, method, r) not in lookup for method in ("genetic_algorithm", comparator) for r in range(4)):
                continue
            first, second, mc_ses = [], [], []
            for repeat in range(4):
                a, b = lookup[(s, "genetic_algorithm", repeat)], lookup[(s, comparator, repeat)]
                ca, cb = counts[a["unit_id"]], counts[b["unit_id"]]
                differences = [x-y for x, y in zip(ca, cb)]
                first.append(a["rumor_mean"]); second.append(b["rumor_mean"])
                mc_ses.append(stdev(differences)/sqrt(len(differences)))
            conditional_by_scenario[(s, comparator)] = (first, second, mc_ses)
            effects.append({"scope": "scenario", "dataset": scenario["dataset"], "scenario_id": s, "rumor_seeds": scenario["rumor_seeds"],
                            "comparator": comparator, **paired_effect(first, second, mc_ses, 45)})
    for dataset in plan["base_protocol"]["datasets"]:
        scenarios = [s["scenario_id"] for s in plan["scenarios"] if s["dataset"] == dataset]
        for comparator in plan["request"]["analysis_policy"]["comparators"]:
            if any((s, comparator) not in conditional_by_scenario for s in scenarios):
                continue
            inputs = [conditional_by_scenario[(s, comparator)] for s in scenarios]
            first = [mean(v[0][r] for v in inputs) for r in range(4)]
            second = [mean(v[1][r] for v in inputs) for r in range(4)]
            ses = [sqrt(sum(v[2][r]**2 for v in inputs))/2 for r in range(4)]
            effects.append({"scope": "dataset_fixed_two_scenario_average", "dataset": dataset, "scenario_id": None,
                            "fixed_scenarios": scenarios, "scenario_weights": [.5, .5], "scenario_population_inference": False,
                            "comparator": comparator, **paired_effect(first, second, ses, 45)})
    return effects


def export_numeric(root: Path, destination: Path) -> tuple[dict, dict, list[dict], list[dict], list[dict], list[dict]]:
    """Recompute all registered numeric outputs from the checkpoint ledger."""
    started = perf_counter()
    plan, state, selections, batches, payloads = read_completed(root)
    audit = audit_records(plan, state, selections, batches)
    rows, counts = primary_rows(plan, state, selections, batches)
    by_scenario = scenario_summaries(plan, rows)
    by_dataset = dataset_summaries(plan, rows, by_scenario)
    comparisons = method_comparisons(plan, rows, counts)
    statuses = Counter(r["status"] for r in rows)
    convergence = []
    for unit, selected in selections.items():
        row = selected["row"]
        if row["algorithm"] == "genetic_algorithm":
            for generation in selected["convergence"]:
                convergence.append({"unit_id": unit, "dataset": row["dataset"], "scenario_id": row["scenario_id"],
                                    "rumor_seeds": row["rumor_seeds"], "repetition_index": row["repetition_index"], **generation})
    runtime = []
    for dataset in plan["base_protocol"]["datasets"]:
        for method in METHODS:
            group = [r for r in rows if r["status"] == "completed" and r["dataset"] == dataset and r["algorithm"] == method]
            runtime.append({"dataset": dataset, "algorithm": method, "completed_result_rows": len(group),
                            "selection_runtime_seconds": sum(r["selection_runtime_seconds"] for r in group),
                            "fitness_MC_seconds_subset_of_selection": sum(r["fitness_MC_seconds_subset_of_selection"] for r in group),
                            "final_evaluation_runtime_seconds": sum(r["final_evaluation_runtime_seconds"] for r in group),
                            "total_runtime_seconds_including_imports_loading_guard": sum(r["total_runtime_seconds"] for r in group),
                            "optimization_evaluator_calls": sum(r["optimization_evaluator_calls"] for r in group),
                            "final_evaluator_calls": sum(r["final_evaluator_calls"] for r in group),
                            "optimization_CIC_simulations": sum(r["optimization_CIC_simulations"] for r in group),
                            "final_CIC_simulations": sum(r["final_CIC_simulations"] for r in group),
                            "total_CIC_simulations": sum(r["CIC_simulations"] for r in group),
                            "peak_worker_RSS_bytes": max((r["worker_peak_RSS_bytes"] for r in group), default=0)})
    skipped = [{**r, "status": "skipped", "execution_status": "skipped_method_cost_limits", "actual_P_size": None, "actual_evaluator_calls": 0,
                "actual_CIC_simulations": 0} for r in plan["matrix"] if not r["method_eligible"]]
    finished_payloads_CIC = sum(r["CIC_simulations"] for r in payloads)
    finished_payloads_calls = sum(r["evaluator_calls"] for r in payloads)
    selection_time = sum(s["timing"]["selection_runtime_seconds"] for s in selections.values())
    final_time = sum(b["final_evaluation_runtime_seconds"] for b in batches.values())
    graph_loading = sum(r["graph_loading_seconds"] for r in payloads)
    worker_sum = sum(r["worker_runtime_seconds"] for r in payloads)
    attempt_sum = sum(a["elapsed_seconds"] for a in state["attempts"])
    summary = {"status": state.get("status", "incomplete"), "planned_primary_results": 144, "completed": statuses["completed"],
               "failed": statuses["failed"], "skipped_primary": statuses["skipped"], "Full_Greedy_skipped": len(skipped),
               "failed_or_interrupted_attempts": sum(a["status"] != "completed" for a in state["attempts"]),
               "completed_selection_units": len(selections), "completed_final_batches": len(batches),
               "actual_evaluator_calls": finished_payloads_calls, "actual_CIC_simulations": finished_payloads_CIC,
               "optimization_evaluator_calls": sum(s["evaluator_calls"] for s in selections.values()),
               "optimization_CIC_simulations": sum(s["CIC_simulations"] for s in selections.values()),
               "final_evaluator_calls": len(batches), "final_CIC_simulations": sum(b["CIC_simulations"] for b in batches.values()),
               "conservative_charged_CIC": state["charged_CIC"],
               "cache_hits": sum(s["selection_details"].get("cache_hit_count", 0) for s in selections.values()),
               "elite_fitness_reuses": sum(s["selection_details"].get("elite_fitness_reuse_count", 0) for s in selections.values()),
               "peak_worker_RSS_bytes": max((p["worker_peak_RSS_bytes"] for p in payloads), default=0),
               "primary_comparison_count": len(comparisons),
               "family_CI_resolved_effects": sum(c["family_CI_excludes_zero"] for c in comparisons),
               "family_CI_unresolved_effects": sum(not c["family_CI_excludes_zero"] for c in comparisons),
               "negative_reduction_result_rows": sum(r.get("spread_reduction_fraction", 0) is not None and r.get("spread_reduction_fraction", 0) < 0 for r in rows),
               "no_global_winner_inferred_from_mean": True, "GA_or_R_retuned_using_main": False,
               "new_experiments_outside_frozen_matrix": 0,
               "runtime": {"selection_optimization_seconds": selection_time,
                           "fitness_MC_seconds_subset_of_selection": sum(s["timing"]["optimization_evaluator_seconds"] for s in selections.values()),
                           "independent_final_evaluation_seconds": final_time, "graph_loading_seconds": graph_loading,
                           "worker_other_seconds": worker_sum-selection_time-final_time-graph_loading,
                           "process_startup_guard_and_output_seconds": attempt_sum-worker_sum,
                           "parent_overhead_seconds": state.get("parent_overhead_seconds", 0),
                           "total_active_execution_seconds": state["active_runtime_seconds"],
                           "analysis_and_tests_excluded_from_algorithm_runtime": True},
               "preflight": {k: v for k, v in plan["preflight"].items() if k != "rows"}}
    if statuses["completed"] == 144:
        if len(comparisons) != 45 or len(by_scenario) != 36 or len(by_dataset) != 18:
            raise ValueError("Complete main results must have all registered summaries/effects")
        if not any(a["status"] != "completed" for a in state["attempts"]):
            if finished_payloads_CIC != state["charged_CIC"] or sum(r["CIC_simulations"] for r in rows) != finished_payloads_CIC:
                raise ValueError("Main physical/summarized CIC totals disagree")
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (("results", rows), ("summary_by_scenario", by_scenario), ("summary_by_dataset", by_dataset),
                        ("method_comparisons", comparisons), ("runtime_summary", runtime), ("GA_convergence", convergence),
                        ("Full_Greedy_skipped", skipped), ("method_status", rows+skipped)):
        atomic_json(destination/f"{name}.json", value)
        write_csv(destination/f"{name}.csv", value)
    (destination/"runs").mkdir(exist_ok=True)
    for row in rows:
        atomic_json(destination/"runs"/f"{row['unit_id']}.json", row)
    final_batch_rows = [{"unit_id": uid, "dataset": b["row"]["dataset"], "scenario_id": b["row"]["scenario_id"],
                         "algorithm": b["row"]["algorithm"], "repetition_index": b["row"]["repetition_index"], "batch": batch,
                         "base_random_seed": b["base_random_seed"], "runtime_seconds": b["final_evaluation_runtime_seconds"],
                         **b["statistics"]} for (uid, batch), b in batches.items()]
    atomic_json(destination/"final_batches.json", final_batch_rows); write_csv(destination/"final_batches.csv", final_batch_rows)
    atomic_json(destination/"observed_artifact_audit.json", audit)
    atomic_json(destination/"metadata.json", json.loads((root/"metadata.json").read_text()))
    atomic_json(destination/"config.json", plan["request"])
    atomic_json(destination/"preflight.json", plan["preflight"])
    atomic_json(destination/"scenarios.json", plan["scenarios"])
    atomic_json(destination/"analysis_policy.json", plan["request"]["analysis_policy"])
    atomic_json(destination/"integrity_after.json", json.loads((root/"integrity_after.json").read_text()))
    atomic_json(destination/"checkpoint_summary.json", {k: v for k, v in state.items() if k not in ("completed", "pending")})
    atomic_json(destination/"selection_barrier.json", json.loads((root/"selection_barrier.json").read_text()) if (root/"selection_barrier.json").exists() else {"status": "incomplete"})
    summary["numeric_analysis_runtime_seconds"] = perf_counter()-started
    atomic_json(destination/"summary.json", summary)
    return plan, summary, rows, by_scenario, by_dataset, comparisons


def create_figures(destination: Path, plan: dict, rows: list[dict], scenario_summary: list[dict], comparisons: list[dict]) -> list[str]:
    """Standalone scientific charts for Chương3; descriptive bars are not winner claims."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    labels = {"no_intervention": "NI", "random": "Random", "degree": "Degree", "pagerank": "PageRank", "candidate_restricted_greedy": "Restricted", "genetic_algorithm": "GA"}
    outputs = []
    figure_dir = destination/"figures"
    figure_dir.mkdir(exist_ok=True)
    def save(fig, name):
        fig.tight_layout()
        for ext in ("png", "svg"):
            path = figure_dir/f"{name}.{ext}"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            outputs.append(path.relative_to(destination).as_posix())
        plt.close(fig)
    summaries = {(r["scenario_id"], r["algorithm"]): r for r in scenario_summary}
    histories = json.loads((destination/"GA_convergence.json").read_text())
    for dataset in plan["base_protocol"]["datasets"]:
        scenarios = [s for s in plan["scenarios"] if s["dataset"] == dataset]
        for kind in ("rumor_mean", "spread_reduction", "runtime"):
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))
            for ax, scenario in zip(axes, scenarios):
                s = scenario["scenario_id"]
                group = [summaries[(s, m)] for m in METHODS]
                x = list(range(6))
                if kind == "rumor_mean":
                    values = [r["mean_rumor"] for r in group]
                    error = [(r["CI95_run_means_high"]-r["CI95_run_means_low"])/2 for r in group]
                    ax.bar(x, values, yerr=error, capsize=4, alpha=.8)
                    for i, method in enumerate(METHODS):
                        vals = [r["rumor_mean"] for r in rows if r["scenario_id"] == s and r["algorithm"] == method]
                        ax.scatter([i]*len(vals), vals, color="black", s=12, zorder=3)
                    ax.set_ylabel("Rumor mean; descriptive 95% CI across4 runs")
                elif kind == "spread_reduction":
                    values = [r["spread_reduction_percent"] for r in group]
                    ax.bar(x, values, alpha=.8)
                    for i, r in enumerate(group):
                        ci = r["spread_reduction_descriptive_CI"]["intervals"]
                        if len(ci) == 1 and None not in ci[0]:
                            lo, hi = ci[0]
                            ax.vlines(i, 100*lo, 100*hi, color="black", lw=1)
                        else:
                            ax.annotate("unbounded CI", (i, values[i]), fontsize=6, rotation=90, va="bottom")
                    ax.axhline(0, color="black", lw=.8)
                    ax.set_ylabel("Spread reduction (%) incl negative values")
                else:
                    a = [r["mean_selection_runtime_seconds"] for r in group]
                    b = [r["mean_final_evaluation_runtime_seconds"] for r in group]
                    ax.bar(x, a, label="Selection")
                    ax.bar(x, b, bottom=a, label="Independent final MC")
                    ax.set_ylabel("Mean seconds/run; load/startup shown in CSV")
                    ax.legend(fontsize=8)
                ax.set_xticks(x, [labels[m] for m in METHODS], rotation=25)
                ax.set_title(f"R={scenario['rumor_seeds']}; p=.03, k=5")
                ax.grid(axis="y", alpha=.2)
            fig.suptitle(f"{dataset}: {kind}; fixed scenarios, no global ranking")
            save(fig, f"{dataset}_{kind}")
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for ax, scenario in zip(axes, scenarios):
            for repeat in range(4):
                h = sorted([h for h in histories if h["scenario_id"] == scenario["scenario_id"] and h["repetition_index"] == repeat], key=lambda h: h["generation"])
                ax.plot([v["generation"] for v in h], [v["best_so_far_fitness"] for v in h], label=f"Run{repeat}")
            ax.set(xlabel="Generation (0=initialization)", ylabel="Best training fitness", title=f"R={scenario['rumor_seeds']}")
            ax.legend(fontsize=8); ax.grid(alpha=.2)
        fig.suptitle(f"{dataset}: GA convergence is diagnostic, not final quality")
        save(fig, f"{dataset}_GA_convergence")
        fig, ax = plt.subplots(figsize=(10, 7))
        effects = [c for c in comparisons if c["dataset"] == dataset]
        for i, effect in enumerate(effects):
            lo, hi, point = effect["family_CI95_low"], effect["family_CI95_high"], effect["mean_difference"]
            ax.plot([lo, hi], [i, i], color="tab:blue" if not effect["family_CI_excludes_zero"] else "tab:orange")
            ax.scatter([point], [i], s=24)
        ax.axvline(0, color="black", lw=1)
        ax.set_yticks(list(range(len(effects))), [f"{c.get('rumor_seeds') or '2R avg'}: GA-{labels[c['comparator']]}" for c in effects], fontsize=8)
        ax.set(xlabel="Final rumor mean difference; simultaneous approximate family45 CI95", title=f"{dataset}: registered comparisons, n4/df3")
        ax.grid(axis="x", alpha=.2)
        save(fig, f"{dataset}_method_comparisons")
    return outputs


def write_report(plan: dict, summary: dict, rows: list[dict], scenario_summary: list[dict], dataset_summary: list[dict], comparisons: list[dict], destination: Path) -> None:
    """Render results with uncertainty, registered scope and explicit limits."""
    complete = summary["completed"] == 144
    sections = []
    for dataset in plan["base_protocol"]["datasets"]:
        group = [r for r in scenario_summary if r["dataset"] == dataset and r["status"] == "completed"]
        table = "\n".join(f"| {r['rumor_seeds']} | {r['algorithm']} | {r['No_Intervention_mean']:.3f} | {r['mean_rumor']:.3f} | {r['SD_between_run_means_including_MC']:.3f} | {r['SE_across_run_means']:.3f} | [{r['CI95_run_means_low']:.3f}, {r['CI95_run_means_high']:.3f}] | {r['mean_conditional_MC_SE']:.3f} | {r['spread_reduction_percent']:.2f}% | {r['mean_selection_runtime_seconds']:.2f} | {r['total_CIC_simulations']} |" for r in group)
        ds = [r for r in dataset_summary if r["dataset"] == dataset]
        dtable = "\n".join(f"| {r['algorithm']} | {r['mean_rumor']:.3f} | [{r['CI95_run_means_low']:.3f}, {r['CI95_run_means_high']:.3f}] | {r['spread_reduction_percent']:.2f}% | [{r['scenario_mean_min']:.3f}, {r['scenario_mean_max']:.3f}] |" for r in ds)
        relevant = [c for c in comparisons if c["dataset"] == dataset]
        ctable = "\n".join(f"| {c.get('rumor_seeds') or '2R average'} | {c['comparator']} | {c['mean_difference']:+.3f} | [{c['family_CI95_low']:+.3f}, {c['family_CI95_high']:+.3f}] | {c['conclusion']} |" for c in relevant)
        resolved = [c for c in relevant if c["family_CI_excludes_zero"]]
        sections.append(f"""### {dataset}

Mỗi method/R có4 independent run estimates, mỗi P có2 final MC batches.
CI trong bảng mean là descriptive pointwise CI qua4 runs, không là interval
đã chỉnh family45. SD giữa run means chứa cả selection variability và MC noise;
conditional MC SE mô tả estimation error của một P đã khóa.
Trong results.csv, rumor_SD_sample là SD của các CIC observations cho từng P;
SD giữa run means trong bảng này là đại lượng khác, không dùng thay cho SD đó.

| R | Method | NI mean | Final mean | SD giữa run means | SE qua4 runs | CI95 qua4 runs | Mean conditional MC SE | Reduction | Selection s/run | Total CIC |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
{table}

Summary trong dataset là equal weights1/2 cho hai fixed R,4 paired bundles.
Không diễn giải CI này là inference trên population tất cả nguồn rumor.

| Method | Equal-R final mean | Descriptive CI95 bundles | Equal mean of scenario reduction ratios | Min/max scenario means |
|---|---:|---|---:|---|
{dtable}

Registered contrasts: GA−comparator; số âm favors GA. Trong scope dataset này,
{len(resolved)}/{len(relevant)} effects có approximate family45 CI loại0.
Mỗi dòng chỉ nói về fixed scope đã ghi; không tạo global winner ranking.

| Scope R | Comparator | GA−comparator | Adjusted family45 CI95 | Evidence |
|---|---|---:|---|---|
{ctable}

![Rumor means {dataset}](docs/main_experiments_results/figures/{dataset}_rumor_mean.png)

![Spread reduction {dataset}](docs/main_experiments_results/figures/{dataset}_spread_reduction.png)

![Runtime {dataset}](docs/main_experiments_results/figures/{dataset}_runtime.png)

![Registered comparisons {dataset}](docs/main_experiments_results/figures/{dataset}_method_comparisons.png)
""")
    ni_table = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {next(s['reachable_count'] for s in plan['scenarios'] if s['scenario_id']==r['scenario_id'])} | {r['mean_rumor']:.3f} | {100*r['mean_rumor']/next(s['node_count'] for s in plan['scenarios'] if s['scenario_id']==r['scenario_id']):.3f}% | {100*r['mean_no_growth_fraction']:.2f}% |" for r in scenario_summary if r["status"] == "completed" and r["algorithm"] == "no_intervention")
    gaps = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {r['algorithm']} | {r['mean_training_fitness_diagnostic']:.3f} | {r['mean_rumor']:.3f} | {r['mean_independent_minus_training']:+.3f} |" for r in scenario_summary if r["status"] == "completed" and r["algorithm"] in ("genetic_algorithm", "candidate_restricted_greedy"))
    rt = summary["runtime"]
    ga_lower = [c for c in comparisons if c["conclusion"] == "GA_lower_rumor_on_this_fixed_scope"]
    comparator_lower = [c for c in comparisons if c["conclusion"] == "comparator_lower_rumor_on_this_fixed_scope"]
    verification_path = destination/"verification.json"
    verification = json.loads(verification_path.read_text()) if verification_path.exists() else None
    verify_text = f"**{verification['tests_passed']}/{verification['tests_run']} tests pass**. {verification['protected_files_checked']} existing protected files, gồm {verification['data_files_checked']} data files, giữ checksum. File set/topology raw/processed không đổi." if verification else "Final tests/checksum/reproducibility verification sẽ được cập nhật sau audit cuối."
    negative = [r for r in rows if r.get("spread_reduction_fraction") is not None and r["spread_reduction_fraction"] < 0]
    negative_summary = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {r['algorithm']} | {r['repetition_index']} | {r['spread_reduction_percent']:.3f}% |" for r in negative)
    if not negative_summary:
        negative_summary = "| — | — | Không có negative reduction trong các completed rows | — | — |"
    (PROJECT_ROOT/"MAIN_EXPERIMENTS_RESULTS.md").write_text(f"""# Main Experiments Results — Frozen Protocol V2

**{summary['status']}**: {summary['completed']}/144 primary result rows completed,
{summary['failed']} failed,{summary['skipped_primary']} primary skipped; thêm
**{summary['Full_Greedy_skipped']} Full Greedy rows skipped** theo cost limits.
Failed/interrupted physical attempts={summary['failed_or_interrupted_attempts']}.
{'Đã hoàn tất đúng ma trận được xác nhận.' if complete else 'Ma trận chưa hoàn tất; nhóm thiếu runs không được đưa vào primary inference.'}
Không thêm experiments ngoài matrix, không retune GA/R/S từ main outcomes.

## 1. Frozen setup, data and execution

[Protocol V2](MAIN_EXPERIMENTS_PROTOCOL_V2.md) thay repetitions5→4 theo lựa
chọn người dùng trước main. [Protocol5runs](MAIN_EXPERIMENTS_PROTOCOL.md) và
artifacts cũ giữ nguyên. Datasets email-Eu-core,ego-Facebook,Wiki-Vote processed;
R lần lượt485/374,714/2733,1961/1795, giữ đúng topology-only reservations.
K5,p=.03,protector-priority,S_opt100; GA N10/G10/.8/.1/tournament3/elite1/cache.
Random/Degree/PageRank/Restricted và NI dùng API đã kiểm chứng. PageRank
alpha.85/tol1e-12/max_iter1000; Restricted pool10 top out-degree/degree ngoàiR.
Full Greedy không được chạy hoặc đổi tên thành Restricted: per-selection
calls email5010/FB20180/Wiki35560 đều vượt limits100calls/2000CIC.

S_eval6000/batch email và2500/batch Facebook/Wiki,B2; mỗi P được final estimate
từ12.000 hoặc5.000 observations. Final schedules giống nhau giữa methods trong
mỗi scenario/repeat, tách optimization và calibration/M7/confirmation namespaces.
Main master2026111109,ordinal11..16,repeat0..3;6 slots còn lại/scenario chưa dùng.
144 selections khóa P và hash trước bất kỳ final call;288 batch checkpoints.
NI control gọi một lần/batch/comparison, không nhân lại cho từng comparator.

## 2. No Intervention và sự khác nhau giữa rumor scenarios

| Dataset | R | Reachable gồmR | NI mean | NI mean/n | NI no-growth observations |
|---|---|---:|---:|---:|---:|
{ni_table}

Giữ và báo cáo tất cả R, gồm Wiki1961 có no-growth probability topology-based
85.87% ở p=.03 dù reachable2316; không chọn lại nguồn sau outcomes. Không lấy
source có mean tốt cho GA để thay source yếu. High/constant reachability
không đại diện uniform rumor population, nhất là Wiki maximum reachable nhỏ
hơn graph. Low/legacy cũ vẫn là supplementary/prior-data, không pha vào main.

## 3. Final quality, uncertainty and registered comparisons

Tổng registered effects={summary['primary_comparison_count']}, trong đó
{summary['family_CI_resolved_effects']} family CIs loại0,
{summary['family_CI_unresolved_effects']} chưa phân biệt được. Primary inference
là paired differences qua4 run estimates/bundles, df3, Bonferroni45 effects:
30 từng scenario +15 equal-weight within-dataset. Pointwise mean plots không
phải primary winner tests. **CI chứa0 là chưa đủ bằng chứng, không equivalence.**
Không suy ra method tốt nhất chỉ từ mean nhỏ nhất, không pool raw rumor counts
giữa ba graph thành global quality conclusion. Practical margin chưa xác nhận,
không claim practical equivalence/global optimality. Family t CIs là xấp xỉ,
n4 và skewed/rare large cascades có giới hạn coverage/power.

Trong các registered contrasts, {len(ga_lower)} effects có bằng chứng GA giảm
rumor hơn comparator và {len(comparator_lower)} effects theo chiều ngược lại.
Các scope scenario và equal-weight dataset có liên hệ với nhau, không phải
những nghiên cứu độc lập để cộng thành số lần một thuật toán chiến thắng.
Những dòng unresolved giữ nguyên kết luận chưa đủ bằng chứng; không dùng chúng
để khẳng định ngang nhau. Các bảng dưới nêu chính xác comparator, nguồn R và CI.

{''.join(sections)}
## 4. Negative reductions, MC uncertainty and algorithm variability

Spread reduction=1−ratio of across-run method/control means cho mỗiR; dataset
summary lấy mean của hai scenario ratios, không ngầm weight theo control size.
Run-level ratios cũng giữ để audit; không thay thế primary ratio-of-means.
**Không clip negative reduction**: {len(negative)} completed rows âm được giữ.
Cùng final seed cho phép ghép cặp observations, nhưng CIC tiêu thụ RNG theo
các activation attempts thực tế; không bảo đảm cùng một số ngẫu nhiên cho
cùng cạnh khi P thay đổi. Vì vậy không suy ra pathwise monotonicity từ seed
chung hoặc diễn giải một reduction âm riêng lẻ là hiệu ứng kỳ vọng đã xác nhận.

| Dataset | R | Method | Run | Reduction âm |
|---|---|---|---:|---:|
{negative_summary}

Descriptive Fieller ratio CIs giữ bounded/unbounded/disjoint confidence sets;
endpoint null nghĩa là unbounded, không phải0. Dataset ratio CI dùng equal sum
hai97.5%Fieller sets, conservative descriptive95% union-bound approximation.
Các ratio intervals không là thêm primary significance tests trong family45.

MC SD/SE mô tả final observations với P cố định. SD giữa4 means còn chứa MC
noise; raw Var(run means)−mean(MC SE²) kể cả âm được giữ, display clipped riêng,
không coi giá trị âm là bằng chứng GA không biến động. NI/Degree/PageRank có
selection variability=0 theo cấu trúc, final repeats đoMC; Random/Greedy-MC/GA
còn có selection variability. Jaccard/unique P counts được lưu riêng. Scenario
heterogeneity là sự khác nhau giữa hai fixed R, không phải extra GA repeats;
report min/max means và per-R effects, không tạo CI trên population all sources.

## 5. Training fitness, convergence and independent quality

| Dataset | R | Optimizer | Training fitness mean | Independent final mean | Final−training mean |
|---|---|---|---:|---:|---:|
{gaps}

GA và Greedy fitness được đánh giá fixedS100 khi lựa chọn, có selection bias;
không dùng làm kết quả thực nghiệm cuối. Elites/cache giữ semantics cũ.
Convergence là generation0..10,4GA runs/R, không dùng điểm training thấp nhất
để đổi cấu hình hoặc chọn lại kết quả main. Dataset plots:

![Email GA convergence](docs/main_experiments_results/figures/email-Eu-core_GA_convergence.png)

![Facebook GA convergence](docs/main_experiments_results/figures/ego-Facebook_GA_convergence.png)

![Wiki GA convergence](docs/main_experiments_results/figures/Wiki-Vote_GA_convergence.png)

## 6. Runtime, CIC cost and checkpoints

Preflight upper3648 evaluator calls/1.392.000CIC; proxy safety+overhead
8889.537s, budget10800s. **Actual {summary['actual_evaluator_calls']} evaluator
calls/{summary['actual_CIC_simulations']:,} CIC**, gồm optimization
{summary['optimization_evaluator_calls']}calls/{summary['optimization_CIC_simulations']:,}CIC;
final{summary['final_evaluator_calls']}calls/{summary['final_CIC_simulations']:,}CIC.
Conservative charged CIC={summary['conservative_charged_CIC']}; unknown partial
work nếu có không được ghi thành actual0. Cache hits={summary['cache_hits']},
elite fitness reuses={summary['elite_fitness_reuses']}; không đếm chúng như
evaluator calls mới. Peak worker={summary['peak_worker_RSS_bytes']/1024**2:.1f}MiB.

| Runtime component đã đo | Giây |
|---|---:|
| Selection/optimization | {rt['selection_optimization_seconds']:.3f} |
| Fitness MC, subset trong selection, không cộng lần hai | {rt['fitness_MC_seconds_subset_of_selection']:.3f} |
| Independent final MC | {rt['independent_final_evaluation_seconds']:.3f} |
| Graph loading | {rt['graph_loading_seconds']:.3f} |
| Worker graph copy/statistics/bookkeeping | {rt['worker_other_seconds']:.3f} |
| Process startup/resource guard/output | {rt['process_startup_guard_and_output_seconds']:.3f} |
| Parent orchestration | {rt['parent_overhead_seconds']:.3f} |
| **Total active execution** | **{rt['total_active_execution_seconds']:.3f}** |

Runtime CSV có selection/final/total theo dataset/method, mỗi result row có
timings riêng. Total gồm load/import/resource guard/JSON, không đồng nhất với
selection. Tests/analysis/plotting tách khỏi algorithm runtime. Atomic ledger
lưu từng selection/batch, verify code/graph/config/P/seed fingerprint khi resume,
không chạy lại units hoàn tất hoặc reset cumulative time/CIC caps. Actual
sequence và selection_barrier được audit, bảo đảm allP before allfinal.

## 7. Verification, reproducibility and limits

{verify_text}
Statistical outputs được tính lại từ raw counts/checkpoints và kiểm tra
consistency; không resimulate main ngoài matrix để tạo thêm observations.
Reproducibility scope: frozen RNG schedules, prior core/adapter determinism
tests, raw/selection hashes, numeric re-aggregation và no-duplicate resume;
không claim đã rerun toàn bộ official MC lần hai. Runtime/hardware scheduling
không được kỳ vọng bit-identical. Prior5 protocol/calibration/screen/confirmation
artifacts được đối chiếu độc lập, không ghi đè.

Giới hạn: chỉ2high/constant R mỗi dataset, p/k cố định,4 independent runs,
S_opt100 noisy fitness, conditional MC accuracy khác nhau giữa P/R, t/Fieller
approximations với heavy tails. Những effects chưa phân biệt giữ unresolved;
không tiếp tục tuning GA hoặc bổ sung experiment sau khi thấy main quality.

Outputs: [results.csv](docs/main_experiments_results/results.csv),
[results.json](docs/main_experiments_results/results.json),
[summary_by_dataset.csv](docs/main_experiments_results/summary_by_dataset.csv),
[summary_by_scenario.csv](docs/main_experiments_results/summary_by_scenario.csv),
[method_comparisons.csv](docs/main_experiments_results/method_comparisons.csv),
[runtime_summary.csv](docs/main_experiments_results/runtime_summary.csv),
[GA_convergence.csv](docs/main_experiments_results/GA_convergence.csv),
[Full_Greedy_skipped.csv](docs/main_experiments_results/Full_Greedy_skipped.csv).
Compact per-run JSON/figures/config/metadata/audits ở docs/main_experiments_results;
complete raw arrays/details/worker jobs/checkpoints ở results/main_experiments_v2
(gitignored), có inventory SHA256. results.csv có144 primary rows, Full skips24
lưu riêng; method_status có168 rows để không nhầm số kết quả hoàn thành.
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT/"results/main_experiments_v2")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT/"docs/main_experiments_results")
    args = parser.parse_args(argv)
    plan, summary, rows, scenario, dataset, comparisons = export_numeric(args.root, args.output)
    if summary["completed"] == 144:
        figures = create_figures(args.output, plan, rows, scenario, comparisons)
        summary["figures"] = figures
    write_report(plan, summary, rows, scenario, dataset, comparisons, args.output)
    atomic_json(args.output/"summary.json", summary)
    atomic_json(args.output/"raw_artifact_inventory.json", {"directory": args.root.relative_to(PROJECT_ROOT).as_posix(),
                "files": {p.relative_to(args.root).as_posix(): sha256_file(p) for p in sorted(args.root.rglob("*")) if p.is_file()}, "gitignored": True})
    print(json.dumps({k: v for k, v in summary.items() if k not in ("figures", "preflight")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
