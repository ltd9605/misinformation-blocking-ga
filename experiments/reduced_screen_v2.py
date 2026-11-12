"""Frozen 45-run OFAT screen with atomic checkpoints and bounded resumptions.

Only orchestration is new: all optimization and MC calls use the verified APIs.
Usage: python -m experiments.reduced_screen_v2 --phase preflight|run
Run again with --phase run to resume the identical schedule, never overwrite it.
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import networkx as nx

from experiments.design_protocol_v1 import load_exported_design, load_protocol
from experiments.pilot_protocol_validation import write_csv, write_json
from experiments.preflight_reduced_screen import GA_KEYS, validate_ofat_pair as validate_old_pair
from src.algorithms import make_seed_plan, select_genetic_algorithm
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic
from src.experiments.calibration import observation_summary
from src.experiments.metadata import environment_metadata
from src.experiments.runner import _plain
from src.experiments.seeds import make_experiment_seed_plan
from src.experiments.sensitivity import FACTORS, computational_preflight, ga_evaluation_upper_bound


def atomic_json(path: Path, value: object) -> None:
    """Publish a complete checkpoint by replacing a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".temporary.json")
    write_json(temporary, value)
    temporary.replace(path)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def protected_snapshot() -> dict:
    """Protect every existing src module, data file and frozen base protocol."""
    paths = list((PROJECT_ROOT/"src").rglob("*.py"))
    paths += [p for p in (PROJECT_ROOT/"data").rglob("*") if p.is_file()]
    paths += [PROJECT_ROOT/p for p in ("main.py", "requirements.txt", "experiments/configs/experiment_protocol_v1.json")]
    return {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p) for p in sorted(paths)}


def audit_previous_matrix() -> dict:
    """Audit planned contrasts; no earlier pilot is reused as a screening run."""
    root = PROJECT_ROOT/"docs/milestone_7_reduced_screen"
    matrix = json.loads((root/"run_matrix.json").read_text())
    pairs = json.loads((root/"OFAT_comparisons.json").read_text())
    by_id = {r["run_id"]: r for r in matrix}
    for pair in pairs:
        validate_old_pair(by_id[pair["reference_run_id"]], by_id[pair["alternative_run_id"]], pair["factor"])
    scenarios = []
    for name in sorted({r["scenario_id"] for r in matrix}):
        rows = [r for r in matrix if r["scenario_id"] == name]
        scenarios.append({"scenario_id": name, "dataset": rows[0]["dataset"], "rumor_seeds": rows[0]["rumor_seeds"],
                          "unique_profiles": sorted({r["profile_id"] for r in rows}), "runs": len(rows),
                          "levels": {f: sorted({r[f] for r in rows}) for f in FACTORS},
                          "three_level_panels": [], "valid_planned_two_level_panels": list(FACTORS)})
    return {"old_reduced_profiles": 5, "blueprint_unique_profiles": 9,
            "allocation": "five selected profiles replicated on each scenario; nine blueprint profiles not divided among datasets",
            "scenarios": scenarios, "validated_pairs": len(pairs), "cross_scenario_pairs": 0,
            "completed_old_screen_runs": 0, "empirical_panel_analysis_available": False}


def validate_pair(reference: dict, alternative: dict, factor: str) -> None:
    """Hold scientific conditions/final seeds fixed; independent optimizer RNGs.

    Unlike the historical matrix, the latest request gives each GA run its own
    optimization seeds. That seed policy is identical for all nine profiles.
    """
    fields = ("scenario_id", "dataset", "rumor_seeds", "k", "p", "tie_breaking", "S_opt", "S_eval",
              "final_batches", "repetition_index", "final_batch_seeds")
    if factor not in FACTORS or any(reference[k] != alternative[k] for k in fields):
        raise ValueError("OFAT changes a non-factor condition")
    if [k for k in GA_KEYS if reference[k] != alternative[k]] != [factor]:
        raise ValueError("OFAT must change exactly one GA factor")


def plan_screen(request: dict) -> dict:
    """Derive all nine profiles, scenario and costs directly from Protocol v1."""
    if request["requested_independent_runs"] != 5 or type(request["requested_independent_runs"]) is not int:
        raise ValueError("V2 fixes five independent GA runs")
    if request["main_experiments_authorized"] or request["full_design_authorized"]:
        raise ValueError("Full/main experiments are outside this screen")
    if request["runtime_overhead_allowance_seconds"] < 0 or request["worker_timeout_seconds"] <= 0:
        raise ValueError("Invalid operational runtime allowances")
    p = load_protocol(PROJECT_ROOT/request["protocol_path"])
    d = load_exported_design(p, PROJECT_ROOT/request["exported_protocol_design"])
    if request["screen_master_seed"] in (p["random_seed_policy"]["master_seed"], 2026111108, request["reserved_main_master_seed"]):
        raise ValueError("Screen must use a fresh seed namespace")
    if request["optimization_seed_policy"] != "distinct_per_profile_and_repetition" or request["final_seed_policy"] != "shared_across_profiles_within_repetition_independent_of_optimization":
        raise ValueError("Unexpected seed policy")
    scenario = next((s for s in d["development"] if s["scenario_id"] == request["scenario_id"]), None)
    # Selection uses topology and No Intervention only, never optimizer scores.
    representative = json.loads((PROJECT_ROOT/"docs/pilot_2_calibration/representatives.json").read_text())["email-Eu-core"]
    if scenario is None or scenario["scenario_id"] != representative["scenario_id"] or scenario["rumor_seeds"] != representative["rumor_seeds"]:
        raise ValueError("Use the existing email representative from control-only calibration")
    if (p["k"], p["p"], p["S_opt"], p["tie_breaking"]) != (5, .03, 100, "protector-priority"):
        raise ValueError("Frozen reference conditions changed")
    profiles = d["profiles"]
    if len(profiles) != 9 or Counter(r["factor"] for r in d["panel_rows"] if r["profile_id"] == "reference") != Counter(FACTORS):
        raise ValueError("Expected nine profiles and a shared reference in four panels")
    preflight = computational_preflight(p, profiles, [scenario], 5, d["rates"], p["design_budget"])
    preflight["overhead_allowance_seconds"] = request["runtime_overhead_allowance_seconds"]
    preflight["projected_seconds_including_overhead"] = preflight["rate_projection_seconds_with_safety"]+request["runtime_overhead_allowance_seconds"]
    if preflight["projected_seconds_including_overhead"] > p["design_budget"]["max_projected_seconds"]:
        preflight["within_declared_budget"] = False
        preflight["budget_reasons"].append("overhead_inclusive_projection_exceeds_budget")
    width = p["random_seed_policy"]["block_width"]
    s_eval, batches = p["S_eval_per_batch"][scenario["dataset"]], p["final_batches"]
    if max(p["S_opt"], s_eval*batches) > width//2:
        raise ValueError("CIC schedule exceeds its reserved seed half-block")
    matrix = []
    for ordinal, profile in enumerate(profiles):
        for repeat in range(5):
            opt_index = (scenario["scenario_index"]+1)*10000+ordinal*100+repeat
            final_index = scenario["scenario_index"]*100+repeat
            opt = make_experiment_seed_plan(request["screen_master_seed"], opt_index, width)
            final = make_experiment_seed_plan(request["screen_master_seed"], final_index, width)
            matrix.append({"run_id": f"{profile['profile_id']}_r{repeat}", "profile_id": profile["profile_id"],
                           "scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                           "k": p["k"], "p": p["p"], "tie_breaking": p["tie_breaking"], "S_opt": p["S_opt"],
                           "S_eval": s_eval, "final_batches": batches, **profile["parameters"],
                           "repetition_index": repeat, "scenario_index": scenario["scenario_index"],
                           "master_seed": request["screen_master_seed"], "optimization_run_index": opt_index,
                           "final_run_index": final_index, "GA_random_seed": opt.ga_random_seed,
                           "GA_operators_seed": make_seed_plan(opt.ga_random_seed, p["S_opt"], opt.optimization_base_random_seed).operators_seed,
                           "optimization_base_random_seed": opt.optimization_base_random_seed,
                           "optimization_seed_stop_exclusive": opt.optimization_base_random_seed+p["S_opt"],
                           "final_batch_seeds": [final.final_base_random_seed+b*s_eval for b in range(batches)],
                           "final_seed_stop_exclusive": final.final_base_random_seed+batches*s_eval,
                           "OFAT_panels": list(FACTORS) if profile["profile_id"] == "reference" else [profile["changed_factor"]]})
    pairs = []
    for repeat in range(5):
        reference = next(r for r in matrix if r["profile_id"] == "reference" and r["repetition_index"] == repeat)
        for row in [r for r in matrix if r["profile_id"] != "reference" and r["repetition_index"] == repeat]:
            factor = row["OFAT_panels"][0]
            validate_pair(reference, row, factor)
            pairs.append({"factor": factor, "repetition_index": repeat, "reference_run_id": reference["run_id"], "alternative_run_id": row["run_id"]})
    return {"request": request, "protocol": p, "scenario": scenario, "scenario_control_evidence": representative,
            "profiles": profiles, "panel_rows": d["panel_rows"], "matrix": matrix, "pairs": pairs,
            "preflight": preflight, "rates": d["rates"], "audit_previous": audit_previous_matrix()}


def run_ga_case(graph: nx.Graph, row: dict) -> dict:
    """Run unchanged GA, freeze its selected P, then independently evaluate it."""
    started = perf_counter()
    core = select_genetic_algorithm(graph, row["rumor_seeds"], row["k"], row["p"], row["S_opt"],
                                    **{k: row[k] for k in GA_KEYS}, random_seed=row["GA_random_seed"],
                                    fitness_base_random_seed=row["optimization_base_random_seed"], tie_breaking=row["tie_breaking"])
    selection_seconds = perf_counter()-started
    counts, batch_results, evaluation_seconds = [], [], 0.0
    for b, seed in enumerate(row["final_batch_seeds"]):
        t0 = perf_counter()
        result = evaluate_cic(graph, row["rumor_seeds"], core.best_protector_nodes, row["p"], row["S_eval"],
                              base_random_seed=seed, tie_breaking=row["tie_breaking"])
        wall = perf_counter()-t0
        values = [r.rumor_count for r in result.raw_results]
        counts.extend(values)
        evaluation_seconds += wall
        batch_results.append({"batch": b, "base_seed": seed, "runtime_seconds": wall,
                              "statistics": observation_summary(values, len(graph)), "rumor_counts": values})
    return {"row": row, "protector_seeds": sorted(core.best_protector_nodes), "training_fitness": core.best_estimated_fitness,
            "selection_runtime_seconds": selection_seconds, "fitness_evaluator_runtime_seconds": core.evaluator_runtime_seconds,
            "final_evaluation_runtime_seconds": evaluation_seconds, "final": observation_summary(counts, len(graph)),
            "final_batches": batch_results, "core_GA_result": _plain(core),
            "evaluator_calls": core.evaluation_count+row["final_batches"],
            "CIC_simulations": core.cic_simulation_count+row["final_batches"]*row["S_eval"]}


def worker(job_path: Path) -> int:
    """One isolated checkpoint unit; a killed worker cannot publish partial JSON."""
    started = perf_counter()
    job = json.loads(job_path.read_text())
    row = job["row"]
    t0 = perf_counter()
    graph = load_processed_graph(PROJECT_ROOT/"data/processed"/row["dataset"])
    load_seconds = perf_counter()-t0
    before = deepcopy(graph)
    nx.freeze(graph)
    if job["kind"] == "GA":
        payload = run_ga_case(graph, row)
    else:
        t0 = perf_counter()
        result = evaluate_cic(graph, row["rumor_seeds"], [], row["p"], row["S_eval"],
                              base_random_seed=job["base_seed"], tie_breaking=row["tie_breaking"])
        values = [r.rumor_count for r in result.raw_results]
        payload = {"row": row, "batch": job["batch"], "base_seed": job["base_seed"], "protector_seeds": [],
                   "runtime_seconds": perf_counter()-t0, "final": observation_summary(values, len(graph)),
                   "rumor_counts": values, "evaluator_calls": 1, "CIC_simulations": row["S_eval"]}
    if not nx.utils.graphs_equal(graph, before):
        raise RuntimeError("Graph changed")
    payload.update(graph_loading_seconds=load_seconds, worker_runtime_seconds=perf_counter()-started,
                   job_fingerprint=job["fingerprint"], status="completed", graph_unchanged=True)
    atomic_json(Path(job["result_path"]), payload)
    return 0


def reconcile_pending(state: dict) -> None:
    """Recover a published result, or conservatively charge unknown interrupted work."""
    pending = state.get("pending")
    if not pending:
        return
    path = Path(pending["result_path"])
    if path.exists():
        result = json.loads(path.read_text())
        if result["job_fingerprint"] != pending["fingerprint"]:
            raise ValueError("Checkpoint result does not match frozen job")
        cic = result["CIC_simulations"]
        if cic > pending["CIC_upper"]:
            raise RuntimeError("Work exceeds declared bound")
        elapsed = pending.get("measured_wall_seconds", result["worker_runtime_seconds"])
        entry = {**pending, "status": "completed", "charged_CIC": cic, "measured_CIC": cic, "elapsed_seconds": elapsed}
        state["completed"][pending["work_id"]] = pending["result_path"]
        state.setdefault("result_sha256", {})[pending["work_id"]] = sha256_file(path)
    else:
        entry = {**pending, "status": "interrupted_or_failed_unknown_partial_work", "charged_CIC": pending["CIC_upper"],
                 "measured_CIC": None, "elapsed_seconds": pending.get("measured_wall_seconds", pending["timeout_seconds"])}
    state["attempts"].append(entry)
    state["charged_CIC"] += entry["charged_CIC"]
    state["active_runtime_seconds"] += entry["elapsed_seconds"]
    state["pending"] = None


def execute(plan: dict, root: Path) -> dict:
    """Resume only the frozen request, preserving completed runs and cumulative caps."""
    if not plan["preflight"]["within_declared_budget"]:
        return {"status": "stopped_at_preflight", "completed": 0}
    if root.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Output cannot be in data")
    root.mkdir(parents=True, exist_ok=True)
    protected = protected_snapshot()
    identity = fingerprint({"plan": plan, "protected": protected, "engine": sha256_file(Path(__file__))})
    checkpoint = root/"checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["fingerprint"] != identity:
            raise ValueError("Code/data/config changed since checkpoint; cannot resume")
        reconcile_pending(state)
        for work_id, path in state["completed"].items():
            if not Path(path).exists() or sha256_file(Path(path)) != state["result_sha256"][work_id]:
                raise ValueError(f"Missing or changed completed checkpoint: {work_id}")
    else:
        if any(root.iterdir()):
            raise ValueError("Output has files but no checkpoint")
        state = {"fingerprint": identity, "started_utc": datetime.now(timezone.utc).isoformat(), "pending": None,
                 "completed": {}, "attempts": [], "charged_CIC": 0, "active_runtime_seconds": 0.0}
        atomic_json(root/"frozen_plan.json", plan)
        atomic_json(root/"integrity_before.json", protected)
        atomic_json(root/"metadata.json", environment_metadata())
    atomic_json(checkpoint, state)
    invocation_started = perf_counter()
    initial_active_seconds = state["active_runtime_seconds"]
    work = []
    for row in plan["matrix"]:
        upper = ga_evaluation_upper_bound({k: row[k] for k in GA_KEYS})*row["S_opt"]+row["S_eval"]*row["final_batches"]
        work.append({"work_id": row["run_id"], "kind": "GA", "row": row, "CIC_upper": upper})
    for repeat in range(5):
        row = next(r for r in plan["matrix"] if r["profile_id"] == "reference" and r["repetition_index"] == repeat)
        for batch, seed in enumerate(row["final_batch_seeds"]):
            work.append({"work_id": f"control_r{repeat}_b{batch}", "kind": "control", "row": row,
                         "batch": batch, "base_seed": seed, "CIC_upper": row["S_eval"]})
    budget = plan["protocol"]["design_budget"]
    for unit in work:
        if unit["work_id"] in state["completed"]:
            continue
        remaining = budget["max_projected_seconds"]-initial_active_seconds-(perf_counter()-invocation_started)
        if remaining <= 0 or state["charged_CIC"]+unit["CIC_upper"] > budget["max_cic_simulations"]:
            state["stop_reason"] = "cumulative_runtime_or_simulations_budget"
            break
        attempt = sum(a["work_id"] == unit["work_id"] for a in state["attempts"])
        result_path = root/"runs"/f"{unit['work_id']}_attempt{attempt}.json"
        job = {**unit, "result_path": str(result_path.resolve())}
        job["fingerprint"] = fingerprint({"identity": identity, "unit": unit})
        job_path = root/"jobs"/f"{unit['work_id']}_attempt{attempt}.json"
        atomic_json(job_path, job)
        pending = {k: job[k] for k in ("work_id", "kind", "CIC_upper", "result_path", "fingerprint")}
        pending["timeout_seconds"] = min(remaining, plan["request"]["worker_timeout_seconds"])
        state["pending"] = pending
        atomic_json(checkpoint, state)  # Reserve unknown work before launching the child.
        t0 = perf_counter()
        try:
            result = subprocess.run([sys.executable, "-B", "-m", "experiments.reduced_screen_v2", "--worker", str(job_path)],
                                    cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=pending["timeout_seconds"], check=False)
            log = result.stdout+result.stderr
        except subprocess.TimeoutExpired:
            log = "worker timed out; partial work charged conservatively"
        state["pending"]["measured_wall_seconds"] = perf_counter()-t0
        (root/"logs").mkdir(exist_ok=True)
        (root/"logs"/f"{unit['work_id']}_attempt{attempt}.txt").write_text(log)
        reconcile_pending(state)
        atomic_json(checkpoint, state)
        print(f"{unit['work_id']}: {state['attempts'][-1]['status']}; completed {len(state['completed'])}/55; active {state['active_runtime_seconds']:.2f}s", flush=True)
        if state["attempts"][-1]["status"] != "completed":
            state["stop_reason"] = "worker_failure_resume_requires_same_frozen_plan"
            break
    after = protected_snapshot()
    atomic_json(root/"integrity_after.json", {"before": protected, "after": after, "unchanged": protected == after})
    if protected != after:
        raise RuntimeError("Protected data/core files changed")
    accounted_workers = state["active_runtime_seconds"]-initial_active_seconds
    elapsed = perf_counter()-invocation_started
    state["parent_overhead_seconds"] = state.get("parent_overhead_seconds", 0.0)+max(0.0, elapsed-accounted_workers)
    state["active_runtime_seconds"] = initial_active_seconds+elapsed
    state["status"] = "completed" if len(state["completed"]) == len(work) else "incomplete"
    if state["status"] == "completed":
        state.pop("stop_reason", None)
    atomic_json(checkpoint, state)
    return state


def export_preflight(plan: dict, destination: Path) -> None:
    """Export the complete reviewable matrix before any screen simulation."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, obj in (("config", plan["request"]), ("preflight", plan["preflight"]), ("matrix", plan["matrix"]),
                      ("profiles", plan["profiles"]), ("OFAT_comparisons", plan["pairs"]), ("audit_previous", plan["audit_previous"]),
                      ("scenario_selection_evidence", plan["scenario_control_evidence"]), ("pilot2_rate_evidence", plan["rates"]),
                      ("analysis_policy", plan["request"]["analysis"])):
        atomic_json(destination/f"{name}.json", obj)
    write_csv(destination/"matrix.csv", plan["matrix"])
    write_csv(destination/"profiles.csv", [{"profile_id": p["profile_id"], **p["parameters"]} for p in plan["profiles"]])
    write_csv(destination/"OFAT_panels.csv", plan["panel_rows"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=PROJECT_ROOT/"experiments/configs/milestone_7_reduced_screen_v2.json")
    parser.add_argument("--phase", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)
    request = json.loads(args.request.read_text())
    plan = plan_screen(request)
    export_preflight(plan, PROJECT_ROOT/request["export_directory"])
    print(json.dumps({k: v for k, v in plan["preflight"].items() if k != "rows"}, indent=2), flush=True)
    if args.phase == "run":
        state = execute(plan, PROJECT_ROOT/request["output_directory"])
        print(json.dumps({k: v for k, v in state.items() if k not in ("completed", "attempts")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
