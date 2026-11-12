"""Only the eight-run Protocol-v1 pilot; no full/reduced sweep dispatcher."""

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from math import sqrt
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import networkx as nx

from experiments.design_protocol_v1 import load_exported_design, load_protocol
from experiments.pilot_protocol_validation import snapshot, write_csv, write_json
from src.algorithms import select_genetic_algorithm
from src.data import load_processed_graph
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic
from src.experiments.calibration import observation_summary, paired_differences
from src.experiments.metadata import environment_metadata
from src.experiments.runner import _plain
from src.experiments.sensitivity import ga_evaluation_upper_bound, variance_components


def selection_worker(job_path: Path) -> int:
    """Run one unchanged GA call in a timeout-controlled child process."""
    started = perf_counter()
    job = json.loads(job_path.read_text())
    protocol = job["protocol"]
    scenario, profile, seeds = job["scenario"], job["profile"], job["seeds"]
    load_started = perf_counter()
    graph = load_processed_graph(PROJECT_ROOT / "data/processed" / scenario["dataset"])
    load_time = perf_counter()-load_started
    before = deepcopy(graph)
    nx.freeze(graph)
    selection_started = perf_counter()
    result = select_genetic_algorithm(graph, scenario["rumor_seeds"], protocol["k"], protocol["p"], protocol["S_opt"],
                                      **profile["parameters"], random_seed=seeds["operators_input_seed"],
                                      fitness_base_random_seed=seeds["optimization_base_seed"], tie_breaking=protocol["tie_breaking"])
    selection_time = perf_counter()-selection_started
    if not nx.utils.graphs_equal(graph, before):
        raise RuntimeError("GA modified graph")
    payload = {"run_id": job["run_id"], "scenario": scenario, "profile": profile, "seeds": seeds,
               "graph_loading_seconds": load_time, "selection_wall_seconds": selection_time,
               "core_GA_result": _plain(result), "worker_seconds_through_result": perf_counter()-started}
    path = Path(job["selection_path"])
    temporary = path.with_suffix(".temporary.json")
    write_json(temporary, payload)
    temporary.replace(path)
    return 0


def execute_pilot(protocol: dict, design: dict, root: Path) -> dict:
    """Guard the frozen pilot scope, select all P, then evaluate two batches."""
    if not protocol["execution_authorization"]["bounded_pilot"]:
        raise ValueError("Bounded pilot is not authorized")
    pilot = protocol["pilot"]
    preflight = design["preflights"]["pilot"]
    schedule = design["pilot_schedule"]
    if not preflight["within_declared_budget"] or len(schedule) > pilot["max_ga_runs"]:
        raise ValueError("Pilot preflight rejected execution")
    if {v["profile"]["profile_id"] for v in schedule} != set(pilot["profile_ids"]):
        raise ValueError("Schedule contains unexpected profiles")
    if any(v["scenario"]["scenario_id"] not in pilot["scenario_ids"] for v in schedule):
        raise ValueError("Schedule contains unexpected scenarios")
    if root.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Do not write into data")
    root.mkdir(parents=True, exist_ok=False)
    for folder in ("jobs", "selections", "raw", "logs"):
        (root/folder).mkdir()
    started = perf_counter()
    before = snapshot()
    write_json(root/"integrity_before.json", before)
    write_json(root/"protocol.json", protocol)
    write_json(root/"preflight.json", preflight)
    write_json(root/"schedule.json", schedule)
    write_json(root/"environment.json", environment_metadata())
    budget = {"charged_CIC": 0, "measured_CIC": 0, "fitness_evaluator_calls": 0,
              "final_evaluator_calls": 0, "control_evaluator_calls": 0, "unknown_partial_work": False}
    execution, selections = [], []
    for job in schedule:
        job = {**job, "protocol": protocol, "selection_path": (root/"selections"/f"{job['run_id']}.json").as_posix()}
        path = root/"jobs"/f"{job['run_id']}.json"
        write_json(path, job)
        upper = ga_evaluation_upper_bound(job["profile"]["parameters"])*protocol["S_opt"]
        remaining = pilot["max_wall_seconds"]-(perf_counter()-started)
        row = {"run_id": job["run_id"], "scenario_id": job["scenario"]["scenario_id"], "dataset": job["scenario"]["dataset"],
               "profile_id": job["profile"]["profile_id"], "independent_run_index": job["independent_run_index"]}
        if remaining <= 0 or budget["charged_CIC"]+upper > pilot["max_cic_simulations"]:
            row.update(status="skipped", reason="pilot_runtime_or_simulation_budget", actual_fitness_CIC=0)
        else:
            worker_started = perf_counter()
            try:
                result = subprocess.run([sys.executable, "-B", "-m", "experiments.pilot_milestone_7", "--worker-selection", str(path)],
                                        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
                                        timeout=min(remaining, pilot["max_selection_seconds_per_run"]))
            except subprocess.TimeoutExpired as error:
                row.update(status="timed_out", reason=str(error), actual_fitness_CIC=None)
                budget["charged_CIC"] += upper
                budget["unknown_partial_work"] = True
            else:
                (root/"logs"/f"{job['run_id']}.log").write_text(result.stdout+result.stderr)
                if result.returncode:
                    row.update(status="failed", reason=result.stderr, actual_fitness_CIC=None)
                    budget["charged_CIC"] += upper
                    budget["unknown_partial_work"] = True
                else:
                    selection = json.loads(Path(job["selection_path"]).read_text())
                    core = selection["core_GA_result"]
                    if core["cic_simulation_count"] > upper:
                        raise RuntimeError("GA work exceeded preflight bound")
                    selections.append({**job, **selection})
                    row.update(status="selected", reason=None, actual_fitness_CIC=core["cic_simulation_count"],
                               selection_wall_seconds=selection["selection_wall_seconds"])
                    budget["charged_CIC"] += core["cic_simulation_count"]
                    budget["measured_CIC"] += core["cic_simulation_count"]
                    budget["fitness_evaluator_calls"] += core["evaluation_count"]
            row["selection_subprocess_wall_seconds"] = perf_counter()-worker_started
        execution.append(row)
        write_json(root/"selection_execution.json", execution)
        write_json(root/"budget.json", budget)
        print(f"Select {job['run_id']}: {row['status']}", flush=True)
    write_json(root/"selection_barrier.json", {"all_selection_attempts_finished_before_any_final": True,
               "finished_at_utc": datetime.now(timezone.utc).isoformat(),
               "protector_sets": {s["run_id"]: s["core_GA_result"]["best_protector_nodes"] for s in selections}})
    graphs = {s["scenario"]["dataset"]: load_processed_graph(PROJECT_ROOT/"data/processed"/s["scenario"]["dataset"]) for s in selections}
    graph_copies = {name: deepcopy(g) for name, g in graphs.items()}
    for g in graphs.values():
        nx.freeze(g)
    controls, control_rows, batch_rows, rows, histories = {}, [], [], [], []
    counts_by_run_batch = {}
    def final_call(scenario, protector, seed, s_eval, call_type):
        rate = design["rates"][scenario["dataset"]]["control_seconds_per_cic" if call_type == "control" else "GA_final_seconds_per_cic"]
        projection = s_eval*rate*protocol["design_budget"]["runtime_safety_factor"]
        if budget["charged_CIC"]+s_eval > pilot["max_cic_simulations"] or perf_counter()-started+projection > pilot["max_wall_seconds"]:
            return None
        estimate = evaluate_cic(graphs[scenario["dataset"]], scenario["rumor_seeds"], protector, protocol["p"], s_eval,
                                base_random_seed=seed, tie_breaking=protocol["tie_breaking"])
        budget["charged_CIC"] += s_eval
        budget["measured_CIC"] += s_eval
        budget[f"{call_type}_evaluator_calls"] += 1
        write_json(root/"budget.json", budget)
        return estimate
    for selection in selections:
        core, scenario = selection["core_GA_result"], selection["scenario"]
        run_id, run = selection["run_id"], selection["independent_run_index"]
        protector = core["best_protector_nodes"]
        n, s_eval = len(graphs[scenario["dataset"]]), protocol["S_eval_per_batch"][scenario["dataset"]]
        pooled, control_counts, evaluation_seconds = [], [], 0.0
        for batch in range(protocol["final_batches"]):
            seed = selection["seeds"]["final_base_seed"]+batch*s_eval
            key = (scenario["scenario_id"], run, batch)
            if key not in controls:
                control = final_call(scenario, [], seed, s_eval, "control")
                if control is None:
                    break
                controls[key] = control
                control_id = f"{scenario['scenario_id']}_r{run}_b{batch}"
                write_json(root/"raw"/f"control_{control_id}.json", {"control_id": control_id, "seed": seed,
                           "raw_results": [asdict(v) for v in control.raw_results]})
                control_rows.append({"control_id": control_id, "scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"],
                                     "independent_run_index": run, "batch": batch, "base_random_seed": seed,
                                     "runtime_seconds": control.runtime_seconds,
                                     **observation_summary([v.rumor_count for v in control.raw_results], n, scenario["reachable_count"])})
            estimate = final_call(scenario, protector, seed, s_eval, "final")
            if estimate is None:
                break
            counts = [v.rumor_count for v in estimate.raw_results]
            counts_by_run_batch[(run_id, batch)] = counts
            pooled.extend(counts)
            control_counts.extend(v.rumor_count for v in controls[key].raw_results)
            evaluation_seconds += estimate.runtime_seconds
            context = {"run_id": run_id, "scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"],
                       "profile_id": selection["profile"]["profile_id"], "independent_run_index": run,
                       "batch": batch, "S_eval_per_batch": s_eval, "base_random_seed": seed,
                       "rumor_seeds": scenario["rumor_seeds"], "protector_seeds": protector}
            write_json(root/"raw"/f"{run_id}_b{batch}.json", {"context": context, "raw_results": [asdict(v) for v in estimate.raw_results]})
            batch_rows.append({**context, "runtime_seconds": estimate.runtime_seconds,
                               **observation_summary(counts, n, scenario["reachable_count"])})
            print(f"Final {run_id} batch={batch}: {len(counts)} simulations", flush=True)
        complete = len(pooled) == s_eval*protocol["final_batches"]
        row = {"run_id": run_id, "scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"],
               "profile_id": selection["profile"]["profile_id"], "independent_run_index": run,
               "status": "completed" if complete else "incomplete_final_budget",
               "rumor_seeds": scenario["rumor_seeds"], "protector_seeds": protector,
               "parameters": selection["profile"]["parameters"], "seeds": selection["seeds"],
               "best_training_fitness": core["best_estimated_fitness"], "generations_run": core["generations_run"],
               "fitness_evaluator_calls": core["evaluation_count"], "fitness_CIC_simulations": core["cic_simulation_count"],
               "cache_hits": core["cache_hit_count"], "elite_fitness_reuses": core["elite_fitness_reuse_count"],
               "graph_loading_seconds": selection["graph_loading_seconds"], "selection_seconds": selection["selection_wall_seconds"],
               "fitness_evaluator_seconds": core["evaluator_runtime_seconds"], "final_evaluation_seconds": evaluation_seconds,
               "S_opt": protocol["S_opt"], "S_eval_per_batch": s_eval, "planned_final_batches": protocol["final_batches"],
               "total_final_simulations": len(pooled), "actual_final_calls": len(pooled)//s_eval}
        if complete:
            stats = observation_summary(pooled, n, scenario["reachable_count"])
            row.update(final_pooled_mean=stats["rumor_mean"], final_pooled_std_population=stats["rumor_std_population"],
                       final_conditional_MC_SE=stats["rumor_SE"], final_pooled_CI95_low=stats["ci95_low"], final_pooled_CI95_high=stats["ci95_high"],
                       final_minus_training=stats["rumor_mean"]-core["best_estimated_fitness"],
                       pooled_control_mean=sum(control_counts)/len(control_counts),
                       spread_reduction_fraction=1-stats["rumor_mean"]/(sum(control_counts)/len(control_counts)))
        rows.append(row)
        for generation in core["history"]:
            histories.append({"run_id": run_id, "scenario_id": scenario["scenario_id"], "profile_id": row["profile_id"],
                              "independent_run_index": run, **{k: v for k, v in generation.items() if k not in ("population", "fitness_values")}})
        write_json(root/"results.json", rows)
    groups = defaultdict(list)
    for row in rows:
        if row["status"] == "completed":
            groups[(row["scenario_id"], row["profile_id"])].append(row)
    variability = []
    for (scenario_id, profile_id), values in groups.items():
        if len(values) >= 2:
            variability.append({"scenario_id": scenario_id, "profile_id": profile_id,
                                **variance_components([v["final_pooled_mean"] for v in values], [v["final_conditional_MC_SE"] for v in values])})
    effects, conditional = [], []
    from scipy.stats import t
    from statistics import mean, stdev
    for scenario_id in sorted({r["scenario_id"] for r in rows}):
        reference = {r["independent_run_index"]: r for r in groups.get((scenario_id, "reference"), [])}
        alternative = {r["independent_run_index"]: r for r in groups.get((scenario_id, "population_size_20"), [])}
        common = sorted(reference.keys() & alternative.keys())
        differences = [reference[i]["final_pooled_mean"]-alternative[i]["final_pooled_mean"] for i in common]
        if len(differences) >= 2:
            se = stdev(differences)/sqrt(len(differences))
            half = float(t.ppf(.975, len(differences)-1))*se
            effects.append({"scenario_id": scenario_id, "paired_independent_GA_runs": len(differences),
                            "reference_minus_N20_mean": mean(differences), "CI95_over_GA_run_differences_low": mean(differences)-half,
                            "CI95_over_GA_run_differences_high": mean(differences)+half, "automatic_winner": None})
        for i in common:
            for batch in range(protocol["final_batches"]):
                conditional.append({"scenario_id": scenario_id, "independent_run_index": i, "batch": batch,
                                    **paired_differences(counts_by_run_batch[(reference[i]["run_id"], batch)],
                                                         counts_by_run_batch[(alternative[i]["run_id"], batch)])})
    for name, values in (("results", rows), ("final_batches", batch_rows), ("controls", control_rows),
                         ("convergence", histories), ("variance_components", variability),
                         ("paired_GA_run_effects", effects), ("conditional_MC_differences", conditional), ("selection_execution", execution)):
        write_csv(root/f"{name}.csv", values)
        write_json(root/f"{name}.json", values)
    for name, graph in graphs.items():
        if not nx.utils.graphs_equal(graph, graph_copies[name]):
            raise RuntimeError("Final evaluation modified graph")
    after = snapshot()
    integrity = {"unchanged": before == after, "files_compared": len(before)}
    write_json(root/"integrity.json", integrity)
    summary = {"purpose": "bounded_milestone7_system_and_timing_pilot_only", "full_sweep_executed": False,
               "main_experiments_executed": False, "completed_GA_runs": sum(r["status"] == "completed" for r in rows),
               "planned_GA_runs": len(schedule), "budget": budget, "wall_seconds_through_exports": perf_counter()-started,
               "integrity": integrity, "all_selections_before_final": True,
               "scope_limitations": "only N10/N20, two development R, two GA runs each; does not establish sensitivity curves or winner",
               "timing_scope": "parent wall includes workers/imports/loading/control/final/logging/exports through primary artifacts; last summary write excluded",
               "inference_unit": "GA run for parameter effects; MC observations conditional on a fixed P for MC CIs"}
    write_json(root/"summary.json", summary)
    if not integrity["unchanged"]:
        raise RuntimeError("Data/core checksum mismatch")
    print(f"Pilot complete: {summary['completed_GA_runs']}/{len(schedule)} GA runs, {budget['measured_CIC']} CIC, {summary['wall_seconds_through_exports']:.3f}s", flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT/"experiments/configs/experiment_protocol_v1.json")
    parser.add_argument("--design-dir", type=Path, default=PROJECT_ROOT/"docs/experiment_protocol_v1")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--worker-selection", type=Path)
    args = parser.parse_args(argv)
    if args.worker_selection:
        return selection_worker(args.worker_selection.resolve())
    protocol = load_protocol(args.protocol.resolve())
    design = load_exported_design(protocol, args.design_dir.resolve())
    output = args.output_dir.resolve() if args.output_dir else (PROJECT_ROOT/protocol["output_directory"]).resolve()
    summary = execute_pilot(protocol, design, output)
    return int(summary["completed_GA_runs"] != summary["planned_GA_runs"])


if __name__ == "__main__":
    raise SystemExit(main())
