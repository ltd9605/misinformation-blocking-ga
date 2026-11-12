"""Staged, resource-bounded Pilot 2; never runs official experiments."""

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import json
from math import isclose, sqrt
from pathlib import Path
from time import perf_counter
from typing import Any

from experiments.pilot_protocol_validation import execute_case, snapshot, write_csv, write_json
from src.data import load_processed_graph
from src.data.specs import PROJECT_ROOT
from src.algorithms import estimate_greedy_cost
from src.evaluation import evaluate_cic
from src.experiments import ExperimentConfig, make_experiment_seed_plan
from src.experiments.calibration import (
    choose_representative, jaccard, observation_summary, paired_differences,
    ranking_diagnostics, reachability_summary, reachable_sizes, sample_reachable_scenarios,
)
from src.experiments.metadata import environment_metadata
from src.experiments.protocol import plan_methods, projected_runtime


class CalibrationStudy:
    """Persist stage journals so interrupted or budget-limited work stays visible."""

    def __init__(self, settings: dict[str, Any], *, create: bool = False):
        self.c = settings
        self.root = Path(settings["output_directory"])
        if create:
            if self.root.is_relative_to((PROJECT_ROOT / "data").resolve()):
                raise ValueError("Do not write into data")
            self.root.mkdir(parents=True, exist_ok=False)
            for name in ("configs", "logs", "controls", "accuracy"):
                (self.root / name).mkdir()
            write_json(self.root / "config.json", settings)
            write_json(self.root / "budget.json", {"charged_cic_simulations": 0, "measured_cic_simulations": 0,
                       "unknown_partial_work": False, "phase_wall_seconds": {}})
            write_json(self.root / "integrity_before.json", snapshot())
            write_json(self.root / "environment.json", environment_metadata())
        elif not self.root.exists():
            raise FileNotFoundError("Run prepare first")
        elif json.loads((self.root / "config.json").read_text()) != settings:
            raise ValueError("Settings differ from frozen study config")
        self.budget = json.loads((self.root / "budget.json").read_text())
        self.graphs = {name: load_processed_graph(PROJECT_ROOT / "data/processed" / name) for name in self.c["datasets"]}
        self.phase_started = perf_counter()

    def save_budget(self) -> None:
        write_json(self.root / "budget.json", self.budget)

    def admission(self, simulations: int, projected_seconds: float = 0.0) -> str | None:
        """Budget charge is actual for successful work, conservative for timeouts."""
        resource = self.c["resources"]
        if self.budget["charged_cic_simulations"] + simulations > resource["max_cic_simulations"]:
            return "simulation_budget_exceeded"
        elapsed = sum(self.budget["phase_wall_seconds"].values()) + perf_counter() - self.phase_started
        if elapsed + projected_seconds > resource["max_wall_seconds"]:
            return "active_execution_wall_budget_exceeded"
        return None

    def charge(self, simulations: int, *, measured: bool = True) -> None:
        self.budget["charged_cic_simulations"] += simulations
        if measured:
            self.budget["measured_cic_simulations"] += simulations
        else:
            self.budget["unknown_partial_work"] = True
        self.save_budget()

    def finish_phase(self, phase: str) -> None:
        self.budget["phase_wall_seconds"][phase] = perf_counter() - self.phase_started
        self.save_budget()

    def seed(self, index: int):
        return make_experiment_seed_plan(self.c["master_seed"], index, self.c["seed_block_size"])

    def prepare(self) -> None:
        nodes, histograms, summaries, scenarios, strata = [], [], {}, [], []
        for name, graph in self.graphs.items():
            started = perf_counter()
            counts = reachable_sizes(graph)
            summary = reachability_summary(counts)
            summary["analysis_runtime_seconds"] = perf_counter() - started
            summaries[name] = summary
            nodes.extend({"dataset": name, "node_id": v, "reachable_count": size,
                          "reachable_excluding_source": size-1, "fraction_of_graph": size / len(graph)} for v, size in sorted(counts.items()))
            histograms.extend({"dataset": name, **row} for row in summary["histogram"])
            selected, groups = sample_reachable_scenarios(counts, name, self.c["master_seed"],
                                                         self.c["samples_per_reachable_stratum"], 4341 if name == "Wiki-Vote" else None)
            scenarios.extend(selected)
            strata.extend(groups)
        write_csv(self.root / "reachable_nodes.csv", nodes)
        write_csv(self.root / "reachable_histogram.csv", histograms)
        write_json(self.root / "reachable_summary.json", summaries)
        write_csv(self.root / "rumor_scenarios.csv", scenarios)
        write_json(self.root / "rumor_scenarios.json", scenarios)
        write_csv(self.root / "reachable_strata.csv", strata)
        # Envelope before knowing propagation outcomes; counts are not timings.
        controls = len(scenarios) * len(self.c["propagation_probabilities"]) * self.c["control_batches"] * self.c["control_batch_S"]
        optimization = final = comparisons = 0
        ga = self.c["ga_parameters"]
        ga_calls = ga["population_size"] + ga["max_generations"] * (ga["population_size"] - ga["elitism_count"])
        restricted_calls = estimate_greedy_cost(self.c["candidate_pool_size"], self.c["k"], 1).evaluation_count
        optimizer_calls = ga_calls + restricted_calls
        for name in self.c["datasets"]:
            levels = self.levels(name)
            optimization += self.c["optimization_repeats"] * sum(levels) * optimizer_calls
            final += self.c["optimization_repeats"] * len(levels) * 6 * self.c["comparison_S_eval"]
            comparisons += self.c["optimization_repeats"] * len(levels)
        accuracy = len(self.graphs) * self.c["accuracy_batches"] * 6 * max(self.c["accuracy_prefixes"])
        smoke = len(self.graphs) * ((7 + restricted_calls) * 2 + 6 * 5)
        plan = {"classification": "preflight_upper_bound_not_measured_runtime",
                "control_scenarios": len(scenarios), "control_simulations": controls,
                "optimization_comparisons": comparisons,
                "optimization_cic_upper_bound": optimization, "comparison_final_cic": final,
                "accuracy_cic_upper_bound": accuracy, "smoke_cic_upper_bound": smoke,
                "total_cic_upper_bound": controls+optimization+final+accuracy+smoke,
                "full_greedy": "skipped_by_explicit_limits; never replaced under Full name",
                "partial_matrix": "all S_opt levels on email/Facebook; Wiki reference S_opt=100 only",
                "runtime_prediction_seconds": None,
                "seed_design": "controls indices>=1000; smoke 500+d; optimization 10*d+repeat (paired across S); accuracy 2000+10*d+batch"}
        # Evaluator calls must be counted separately from simulations.
        plan["optimization_evaluator_upper_bound"] = comparisons * optimizer_calls
        write_json(self.root / "preflight.json", plan)
        self.finish_phase("prepare")
        print(f"Prepared {len(scenarios)} scenarios; upper bound {plan['total_cic_upper_bound']} CIC", flush=True)

    def levels(self, dataset: str) -> list[int]:
        return self.c["S_opt_levels"] if dataset in self.c["full_S_opt_grid_datasets"] else [self.c["reference_S_opt"]]

    def controls(self) -> None:
        if (self.root / "control_execution.json").exists():
            raise FileExistsError("Controls already executed")
        scenarios = json.loads((self.root / "rumor_scenarios.json").read_text())
        execution, grouped = [], defaultdict(list)
        index = 1000
        for scenario in scenarios:
            name, graph = scenario["dataset"], self.graphs[scenario["dataset"]]
            for p in self.c["propagation_probabilities"]:
                for batch in range(self.c["control_batches"]):
                    s = self.c["control_batch_S"]
                    plan = self.seed(index)
                    case_id = f"{scenario['scenario_id']}_p{p:g}_b{batch}"
                    row = {"dataset": name, "scenario_id": scenario["scenario_id"], "p": p,
                           "batch": batch, "rumor_seeds": scenario["rumor_seeds"],
                           "seed_index": index, "base_random_seed": plan.final_base_random_seed,
                           "planned_evaluator_calls": 1, "planned_cic_simulations": s}
                    index += 1
                    reason = self.admission(s)
                    if reason:
                        row.update(status="skipped", reason=reason, actual_cic_simulations=0)
                    else:
                        result = evaluate_cic(graph, scenario["rumor_seeds"], [], p, s,
                                              base_random_seed=plan.final_base_random_seed, tie_breaking=self.c["tie_breaking"])
                        counts = [v.rumor_count for v in result.raw_results]
                        raw = [asdict(v) for v in result.raw_results]
                        write_json(self.root / "controls" / f"{case_id}.json", {"context": row, "raw_results": raw})
                        self.charge(s)
                        row.update(status="completed", reason=None, actual_cic_simulations=s,
                                   runtime_seconds=result.runtime_seconds,
                                   **observation_summary(counts, len(graph), scenario["reachable_count"]))
                        grouped[(scenario["scenario_id"], p)].extend(counts)
                    execution.append(row)
                    write_json(self.root / "control_execution.json", execution)
                print(f"Control {scenario['scenario_id']} p={p}: {execution[-1]['status']}", flush=True)
        pooled = []
        for scenario in scenarios:
            for p in self.c["propagation_probabilities"]:
                counts = grouped[(scenario["scenario_id"], p)]
                if counts:
                    runtime = sum(r.get("runtime_seconds", 0) for r in execution if r["scenario_id"] == scenario["scenario_id"] and r["p"] == p)
                    pooled.append({**scenario, "p": p, "runtime_seconds": runtime,
                                   "seconds_per_cic": runtime / len(counts),
                                   **observation_summary(counts, len(self.graphs[scenario["dataset"]]), scenario["reachable_count"])})
        write_csv(self.root / "control_batches.csv", execution)
        write_csv(self.root / "control_summary.csv", pooled)
        write_json(self.root / "control_summary.json", pooled)
        gate = self.c["representative_gate"]
        representatives = {name: choose_representative([r for r in pooled if r["dataset"] == name],
                            [s for s in scenarios if s["dataset"] == name], min_fraction=gate["min_graph_fraction"],
                            max_fraction=gate["max_graph_fraction"], max_reachable_fraction=gate["max_reachable_fraction"])
                           for name in self.graphs}
        write_json(self.root / "representatives.json", representatives)
        self.finish_phase("controls")

    def comparison(self, name: str, representative: dict, repeat: int, s: int, *, smoke: bool = False) -> tuple[ExperimentConfig, list[dict]]:
        d = self.c["datasets"].index(name)
        values = {"dataset": name, "rumor_seeds": representative["rumor_seeds"], "k": self.c["k"],
                  "p": representative["p"], "tie_breaking": self.c["tie_breaking"], "S_opt": 2 if smoke else s,
                  "S_eval": 5 if smoke else self.c["comparison_S_eval"],
                  "random_seed": self.c["master_seed"], "independent_run_index": 500+d if smoke else 10*d+repeat,
                  "seed_block_size": self.c["seed_block_size"], "purpose": "pilot2_calibration_only",
                  "ga_parameters": deepcopy(self.c["ga_parameters"]), "pagerank_parameters": self.c["pagerank_parameters"],
                  "candidate_restriction": {"method": "degree", "size": self.c["candidate_pool_size"]},
                  "limits": self.c["limits"], "save_raw_observations": True,
                  "output_directory": (self.root / "runs" / (f"smoke_{name}" if smoke else f"{name}_S{s}_r{repeat}")).as_posix()}
        if smoke:
            values["ga_parameters"].update(population_size=4, max_generations=1, tournament_size=2)
        return plan_methods(self.graphs[name], values)

    def optimize(self) -> None:
        if (self.root / "optimization_execution.json").exists():
            raise FileExistsError("Optimization stage already executed")
        representatives = json.loads((self.root / "representatives.json").read_text())
        plans = []
        for name in self.graphs:
            config, estimates = self.comparison(name, representatives[name], 0, 2, smoke=True)
            plans.append({"case_id": f"smoke_{name}", "dataset": name, "S_opt": 2, "repeat": 0, "phase": "smoke",
                          "config": config.to_dict(), "preflight": estimates})
        for s in self.c["S_opt_levels"]:
            for name in self.graphs:
                if s not in self.levels(name):
                    continue
                for repeat in range(self.c["optimization_repeats"]):
                    config, estimates = self.comparison(name, representatives[name], repeat, s)
                    plans.append({"case_id": f"{name}_S{s}_r{repeat}", "dataset": name, "S_opt": s, "repeat": repeat,
                                  "phase": "optimization", "config": config.to_dict(), "preflight": estimates})
        write_json(self.root / "optimization_preflight.json", plans)  # Frozen before any optimizer.
        for plan in plans:
            write_json(self.root / "configs" / f"{plan['case_id']}.json", plan["config"])
        execution, smokes = [], {}
        for plan in plans:
            costs = [r for r in plan["preflight"] if r["status"] == "planned"]
            upper = sum(r["optimization_cic_simulation_upper_bound"]+r["final_cic_simulations"] for r in costs)
            projection = 0.0
            reason = None
            if plan["phase"] != "smoke":
                if plan["dataset"] not in smokes:
                    reason = "smoke_failed_or_skipped"
                else:
                    projection = projected_runtime(smokes[plan["dataset"]], plan["preflight"], self.c["resources"]["runtime_safety_factor"])
                    if projection > self.c["resources"]["max_comparison_wall_seconds"]:
                        reason = "projected_runtime_exceeds_per_comparison_cap"
            reason = reason or self.admission(upper, projection)
            row = {key: value for key, value in plan.items() if key not in ("config", "preflight")}
            row.update(cic_upper_bound=upper, projected_runtime_seconds=projection, actual_cic_simulations=0)
            if reason:
                row.update(status="skipped", reason=reason, run_directory=None, subprocess_wall_seconds=0.0)
            else:
                remaining = self.c["resources"]["max_wall_seconds"] - sum(self.budget["phase_wall_seconds"].values()) - (perf_counter()-self.phase_started)
                result = execute_case(ExperimentConfig.from_dict(plan["config"]), self.root / "configs" / f"{plan['case_id']}.json",
                                      min(remaining, self.c["resources"]["max_comparison_wall_seconds"]), self.root / "logs")
                row.update(result)
                if row["status"] == "completed":
                    summary = json.loads((Path(row["run_directory"]) / "summary.json").read_text())
                    row["actual_cic_simulations"] = summary["total_cic_simulations"]
                    self.charge(row["actual_cic_simulations"])
                    if plan["phase"] == "smoke":
                        smokes[plan["dataset"]] = summary
                else:
                    row["actual_cic_simulations"] = None
                    self.charge(upper, measured=False)
            execution.append(row)
            write_json(self.root / "optimization_execution.json", execution)
            write_csv(self.root / "optimization_execution.csv", execution)
            print(f"{row['case_id']}: {row['status']} ({row['subprocess_wall_seconds']:.3f}s) {row['reason'] or ''}", flush=True)
        self.finish_phase("optimize")

    def revisit_admission(self) -> None:
        """Revisit runtime deferrals using measured cost scaling, never quality.

        Preserve the original journal and unchanged hard caps. Tiny-smoke
        uncached upper projections can overestimate cached GA costs. Use the
        worst observed selection-time/S plus worst final/overhead, safety margin
        unchanged. Remaining over-cap cases stay skipped with explicit evidence.
        """
        if (self.root / "admission_revision.json").exists():
            raise FileExistsError("Admission revision already recorded")
        cases = json.loads((self.root / "optimization_execution.json").read_text())
        write_json(self.root / "optimization_initial_execution.json", cases)
        revised = []
        for case in cases:
            if case["status"] != "skipped" or case["reason"] != "projected_runtime_exceeds_per_comparison_cap":
                continue
            evidence = [v for v in cases if v["status"] == "completed" and v["phase"] == "optimization"
                        and v["dataset"] == case["dataset"]]
            if not evidence:
                continue
            times = [(v["S_opt"], json.loads((Path(v["run_directory"])/"summary.json").read_text())["timings"])
                     for v in evidence]
            selection_per_S = max(t["selection_optimization_seconds"] / s for s, t in times)
            final = max(t["final_evaluation_seconds"] for _, t in times)
            overhead = max(t["total_experiment_runtime_seconds"]-t["selection_optimization_seconds"]-t["final_evaluation_seconds"] for _, t in times)
            projection = self.c["resources"]["runtime_safety_factor"] * (selection_per_S*case["S_opt"]+final+overhead)
            revision = {"case_id": case["case_id"], "original_projected_seconds": case["projected_runtime_seconds"],
                        "revised_projected_seconds": projection, "evidence_case_ids": [v["case_id"] for v in evidence],
                        "rule": "worst measured selection_seconds/S and final/overhead; no quality metrics used",
                        "hard_cap_unchanged_seconds": self.c["resources"]["max_comparison_wall_seconds"]}
            reason = self.admission(case["cic_upper_bound"], projection)
            if projection > self.c["resources"]["max_comparison_wall_seconds"]:
                reason = "revised_measured_cost_projection_still_exceeds_comparison_cap"
            case["initial_admission_reason"] = case["reason"]
            case["projected_runtime_seconds"] = projection
            if reason:
                case["reason"] = reason
                revision.update(status="skipped", reason=reason)
            else:
                config = ExperimentConfig.from_dict(json.loads((self.root/"configs"/f"{case['case_id']}.json").read_text()))
                write_json(self.root / "admission_revision.json", [*revised, {**revision, "status": "admitted_before_execution"}])
                remaining = self.c["resources"]["max_wall_seconds"]-sum(self.budget["phase_wall_seconds"].values())-(perf_counter()-self.phase_started)
                case.update(execute_case(config, self.root/"configs"/f"{case['case_id']}.json",
                                         min(remaining, self.c["resources"]["max_comparison_wall_seconds"]), self.root/"logs"))
                if case["status"] == "completed":
                    summary = json.loads((Path(case["run_directory"])/"summary.json").read_text())
                    case["actual_cic_simulations"] = summary["total_cic_simulations"]
                    self.charge(case["actual_cic_simulations"])
                else:
                    case["actual_cic_simulations"] = None
                    self.charge(case["cic_upper_bound"], measured=False)
                revision.update(status=case["status"], reason=case["reason"])
            revised.append(revision)
            write_json(self.root / "admission_revision.json", revised)
            write_json(self.root / "optimization_execution.json", cases)
            write_csv(self.root / "optimization_execution.csv", cases)
            print(f"Admission revision {case['case_id']}: {case['status']} projected={projection:.1f}s", flush=True)
        write_json(self.root / "admission_revision.json", revised)
        self.finish_phase("revisit_admission")

    def accuracy(self) -> None:
        if (self.root / "accuracy_execution.json").exists():
            raise FileExistsError("Accuracy stage already executed")
        cases = json.loads((self.root / "optimization_execution.json").read_text())
        representatives = json.loads((self.root / "representatives.json").read_text())
        execution, rows, pairs, ranks = [], [], [], []
        for d, name in enumerate(self.graphs):
            reference = next((v for v in cases if v["dataset"] == name and v["phase"] == "optimization"
                              and v["S_opt"] == self.c["reference_S_opt"] and v["repeat"] == 0 and v["status"] == "completed"), None)
            if reference is None:
                execution.append({"dataset": name, "status": "skipped", "reason": "reference_S100_repeat0_not_completed"})
                continue
            source = json.loads((Path(reference["run_directory"]) / "summary.json").read_text())
            representative = representatives[name]
            graph = self.graphs[name]
            for batch in range(self.c["accuracy_batches"]):
                seed = self.seed(2000+10*d+batch).final_base_random_seed
                samples: dict[int, dict[str, list[int]]] = defaultdict(dict)
                for result in source["results"]:
                    method = result["algorithm"]
                    cumulative, runtime, calls = [], 0.0, 0
                    for prefix in self.c["accuracy_prefixes"]:
                        offset = len(cumulative)
                        count = prefix-offset
                        # Use a measured rate for this method/config; allow a margin.
                        rate = result["final_evaluation_runtime_seconds"] / self.c["comparison_S_eval"]
                        projection = rate*count*self.c["resources"]["runtime_safety_factor"]
                        reason = self.admission(count, projection)
                        context = {"dataset": name, "scenario_id": representative["scenario_id"], "p": representative["p"],
                                   "batch": batch, "algorithm": method, "S_eval": prefix,
                                   "rumor_seeds": representative["rumor_seeds"], "protector_seeds": result["protector_seeds"],
                                   "base_random_seed": seed, "optimization_base_random_seed": result["optimization_base_random_seed"]}
                        if reason:
                            execution.append({**context, "status": "skipped", "reason": reason, "actual_cic_simulations": 0})
                            continue
                        estimate = evaluate_cic(graph, representative["rumor_seeds"], result["protector_seeds"], representative["p"], count,
                                                base_random_seed=seed+offset, tie_breaking=self.c["tie_breaking"])
                        self.charge(count)
                        cumulative.extend({**asdict(v), "simulation_index": offset+v.simulation_index} for v in estimate.raw_results)
                        runtime += estimate.runtime_seconds
                        calls += 1
                        counts = [v["rumor_count"] for v in cumulative]
                        samples[prefix][method] = counts
                        rows.append({**context, **observation_summary(counts, len(graph), representative["reachable_count"]),
                                     "runtime_prefix_MC_seconds": runtime, "prefix_evaluator_calls": calls,
                                     "optimization_fitness": result["optimization_best_estimated_fitness"],
                                     "final_minus_optimization": (sum(counts)/len(counts)-result["optimization_best_estimated_fitness"])
                                         if result["optimization_best_estimated_fitness"] is not None else None})
                        execution.append({**context, "status": "completed", "reason": None, "actual_cic_simulations": count,
                                          "increment_runtime_seconds": estimate.runtime_seconds})
                        write_json(self.root / "accuracy_execution.json", execution)
                    write_json(self.root / "accuracy" / f"{name}_b{batch}_{method}.json", {"context": context, "raw_results": cumulative})
                    print(f"Accuracy {name} batch={batch} {method}: S={len(cumulative)}", flush=True)
                for prefix, methods in samples.items():
                    order, comparisons = ranking_diagnostics(methods)
                    ranks.append({"dataset": name, "batch": batch, "S_eval": prefix, "order": order, "method_count": len(order)})
                    pairs.extend({"dataset": name, "batch": batch, "S_eval": prefix, **row} for row in comparisons)
        write_json(self.root / "accuracy_execution.json", execution)
        write_csv(self.root / "accuracy_execution.csv", execution)
        write_csv(self.root / "accuracy_statistics.csv", rows)
        write_json(self.root / "accuracy_statistics.json", rows)
        write_csv(self.root / "accuracy_pairwise.csv", pairs)
        write_csv(self.root / "accuracy_ranking.csv", ranks)
        self.finish_phase("accuracy")

    def summarize(self) -> None:
        cases = json.loads((self.root / "optimization_execution.json").read_text())
        results, histories, pairwise, ranks, stability = [], [], [], [], []
        observations, summaries = {}, {}
        for case in cases:
            if case["status"] != "completed":
                continue
            context = {key: case[key] for key in ("dataset", "S_opt", "repeat", "phase", "case_id")}
            directory = Path(case["run_directory"])
            summary = json.loads((directory / "summary.json").read_text())
            summaries[case["case_id"]] = summary
            results.extend({**context, **row} for row in summary["results"])
            import csv
            with (directory / "convergence.csv").open(newline="") as stream:
                histories.extend({**context, **row} for row in csv.DictReader(stream))
            with (directory / "raw_observations.csv").open(newline="") as stream:
                by_method = defaultdict(list)
                for row in csv.DictReader(stream):
                    by_method[row["algorithm"]].append(int(row["rumor_count"]))
            observations[case["case_id"]] = by_method
            if case["phase"] == "optimization":
                order, pairs = ranking_diagnostics(by_method)
                ranks.append({**context, "order": order, "uncertain_pairs": sum(v["unresolved_at_pointwise_95"] for v in pairs),
                              "pair_count": len(pairs)})
                pairwise.extend({**context, **row} for row in pairs)
        from itertools import combinations
        completed = [c for c in cases if c["phase"] == "optimization" and c["status"] == "completed"]
        for a, b in combinations(completed, 2):
            if a["dataset"] != b["dataset"] or (a["repeat"] != b["repeat"] and a["S_opt"] != b["S_opt"]):
                continue
            for method in ("genetic_algorithm", "candidate_restricted_greedy"):
                x = next(r for r in summaries[a["case_id"]]["results"] if r["algorithm"] == method)
                y = next(r for r in summaries[b["case_id"]]["results"] if r["algorithm"] == method)
                row = {"dataset": a["dataset"], "algorithm": method, "first_S_opt": a["S_opt"], "second_S_opt": b["S_opt"],
                       "first_repeat": a["repeat"], "second_repeat": b["repeat"],
                       "comparison_type": "paired_S_opt_change" if a["repeat"] == b["repeat"] else "independent_repeat_same_S",
                       "protector_jaccard": jaccard(x["protector_seeds"], y["protector_seeds"]),
                       "first_protector_seeds": x["protector_seeds"], "second_protector_seeds": y["protector_seeds"],
                       "first_final_mean": x["rumor_mean"], "second_final_mean": y["rumor_mean"]}
                if a["repeat"] == b["repeat"]:
                    row.update(paired_differences(observations[a["case_id"]][method], observations[b["case_id"]][method]))
                stability.append(row)
        write_csv(self.root / "optimization_results.csv", results)
        write_json(self.root / "optimization_results.json", results)
        write_csv(self.root / "convergence.csv", histories)
        write_csv(self.root / "optimization_pairwise.csv", pairwise)
        write_csv(self.root / "optimization_ranking.csv", ranks)
        write_csv(self.root / "protector_stability.csv", stability)
        before, after = json.loads((self.root / "integrity_before.json").read_text()), snapshot()
        integrity = {"unchanged": before == after, "files_compared": len(before),
                     "changes": sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))}
        write_json(self.root / "integrity.json", integrity)
        self.finish_phase("summarize")
        summary = {"purpose": self.c["purpose"], "official_experiment": False, "budget": self.budget, "integrity": integrity,
                   "completed_optimization_comparisons": sum(c["status"] == "completed" and c["phase"] == "optimization" for c in cases),
                   "optimization_case_statuses": cases,
                   "representatives": json.loads((self.root / "representatives.json").read_text())}
        write_json(self.root / "summary.json", summary)
        if not integrity["unchanged"]:
            raise RuntimeError("Core/data integrity failed")
        print(f"Summary: measured CIC={self.budget['measured_cic_simulations']}, integrity={integrity['unchanged']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "experiments/configs/pilot_2_calibration.json")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--phase", choices=("prepare", "controls", "optimize", "revisit_admission", "accuracy", "summarize", "all"), default="all")
    args = parser.parse_args(argv)
    path = args.config.resolve()
    settings = json.loads(path.read_text())
    destination = args.output_dir.resolve() if args.output_dir else (path.parent / settings["output_directory"]).resolve()
    settings["output_directory"] = destination.as_posix()
    if settings["accuracy_prefixes"] != sorted(set(settings["accuracy_prefixes"])):
        raise ValueError("Accuracy prefixes must be strictly increasing")
    if max(settings["accuracy_prefixes"]) > settings["seed_block_size"] // 2:
        raise ValueError("Final samples exceed seed block half")
    phases = ("prepare", "controls", "optimize", "revisit_admission", "accuracy", "summarize") if args.phase == "all" else (args.phase,)
    for phase in phases:
        study = CalibrationStudy(settings, create=phase == "prepare")
        getattr(study, phase)()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
