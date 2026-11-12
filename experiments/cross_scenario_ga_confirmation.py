"""Preflight and checkpointed confirmation of three frozen GA configurations.

No simulator or optimizer is implemented here. The V2 worker and its verified
GA/evaluate_cic bridge are reused, with a new frozen scenario/seed schedule.
"""

import argparse
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from random import Random
import resource
import subprocess
import sys
from threading import Event, Thread
from time import perf_counter

from experiments.design_protocol_v1 import load_exported_design, load_protocol
from experiments.pilot_protocol_validation import write_csv
from experiments.reduced_screen_v2 import (
    GA_KEYS, atomic_json, fingerprint, protected_snapshot, reconcile_pending, worker as verified_worker,
)
from src.algorithms import make_seed_plan
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.metadata import environment_metadata
from src.experiments.seeds import make_experiment_seed_plan
from src.experiments.sensitivity import computational_preflight, ga_evaluation_upper_bound


def peak_rss_bytes() -> int:
    """Normalize ru_maxrss (bytes on Darwin, KiB on Linux)."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value*1024)


def memory_probe(dataset: str) -> dict:
    """Measure graph plus deepcopy footprint without GA or diffusion calls."""
    graph = load_processed_graph(PROJECT_ROOT/"data/processed"/dataset)
    copy = deepcopy(graph)
    return {"dataset": dataset, "nodes": len(graph), "edges": graph.number_of_edges(),
            "directed": graph.is_directed(), "graph_and_copy_peak_RSS_bytes": peak_rss_bytes(),
            "copy_nodes": len(copy), "diffusion_calls": 0}


def reserve_main_scenarios(protocol: dict, request: dict, old_scenarios: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sample untouched actual IDs uniformly inside Pilot-2 topology strata.

    All earlier R IDs are excluded. No spread or algorithm scores are read.
    These are reservations/proposals, not approval to run main experiments.
    """
    counts = defaultdict(dict)
    with (PROJECT_ROOT/"docs/pilot_2_calibration/reachable_nodes.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            counts[row["dataset"]][int(row["node_id"])] = int(row["reachable_count"])
    reserved, schedule = [], []
    for dataset in protocol["datasets"]:
        sizes = counts[dataset]
        maximum = max(sizes.values())
        stratum = "constant" if min(sizes.values()) == maximum else "high"
        excluded = {v for s in old_scenarios if s["dataset"] == dataset for v in s["rumor_seeds"]}
        eligible = sorted(v for v, reach in sizes.items() if v not in excluded and (stratum == "constant" or reach*3 > 2*maximum))
        seed = int.from_bytes(hashlib.sha256(f"confirmation-main-topology-v1:{request['main_holdout_sampling_master_seed']}:{dataset}:{stratum}".encode()).digest()[:8], "big")
        if len(eligible) < request["reserved_main_scenarios_per_dataset"]:
            raise ValueError("Insufficient unseen topology-stratum candidates")
        for draw, node in enumerate(Random(seed).sample(eligible, request["reserved_main_scenarios_per_dataset"])):
            ordinal = len(old_scenarios)+len(reserved)
            scenario = {"scenario_id": f"main_reserved_{dataset}_{stratum}_{draw}", "scenario_index": ordinal,
                        "dataset": dataset, "rumor_seeds": [node], "stratum": stratum, "reachable_count": sizes[node],
                        "node_count": len(sizes), "sampling_seed": seed, "excluded_old_R_ids": sorted(excluded),
                        "role": "proposed_official_holdout_unobserved", "diffusion_observations_generated": 0,
                        "selection_rule": "uniform_actual_IDs_in_same_Pilot2_stratum_excluding_all_previous_R"}
            reserved.append(scenario)
            for repeat in range(request["reserved_main_run_slots"]):
                seeds = make_experiment_seed_plan(request["reserved_main_master_seed"], ordinal*100+repeat, protocol["random_seed_policy"]["block_width"])
                schedule.append({"scenario_id": scenario["scenario_id"], "dataset": dataset, "rumor_seeds": [node],
                                 "repetition_index": repeat, "master_seed": seeds.master_seed,
                                 "block_start": seeds.block_start, "GA_random_seed": seeds.ga_random_seed,
                                 "optimization_base_random_seed": seeds.optimization_base_random_seed,
                                 "final_base_random_seed": seeds.final_base_random_seed,
                                 "status": "reserved_not_executed", "main_run_count_confirmed": False})
    return reserved, schedule


def validate_confirmation_pair(reference: dict, alternative: dict) -> None:
    """Prevent confounding a population contrast with graph/R/other GA changes."""
    common = ("dataset", "scenario_id", "rumor_seeds", "k", "p", "tie_breaking", "S_opt", "S_eval",
              "final_batches", "repetition_index", "final_batch_seeds")
    if any(reference[k] != alternative[k] for k in common):
        raise ValueError("Confirmation comparison changes a non-population condition")
    if [k for k in GA_KEYS if reference[k] != alternative[k]] != ["population_size"]:
        raise ValueError("Only population may change")


def build_plan(request: dict, probes: list[dict]) -> dict:
    """Freeze the 27-run plan and retain Protocol-v1 budgets/reference values."""
    if request["main_experiments_authorized"] or request["full_design_authorized"]:
        raise ValueError("Main/full design are outside confirmation")
    if request["independent_runs"] != 3 or type(request["independent_runs"]) is not int:
        raise ValueError("Confirmation fixes three repetitions")
    if request["profile_ids"] != ["reference", "population_size_20", "population_size_40"]:
        raise ValueError("Unexpected profiles")
    p = load_protocol(PROJECT_ROOT/request["protocol_path"])
    d = load_exported_design(p, PROJECT_ROOT/request["exported_protocol_design"])
    if request["scenario_ids"] != p["validation_scenario_ids"]:
        raise ValueError("Use the three predeclared algorithm-outcome-validation scenarios")
    if request["master_seed"] in (p["random_seed_policy"]["master_seed"], 2026111108, 2026111110, request["reserved_main_master_seed"]):
        raise ValueError("Confirmation needs a distinct master namespace")
    if request["runtime_overhead_allowance_seconds"] < 0 or request["worker_RSS_limit_bytes"] <= 0 or request["worker_timeout_seconds"] <= 0 or request["memory_poll_seconds"] <= 0:
        raise ValueError("Invalid operational limits")
    if request["optimization_seed_policy"] != "distinct_per_profile_and_repetition" or request["final_seed_policy"] != "shared_across_profiles_within_scenario_repetition":
        raise ValueError("Seed policy changed")
    if (p["k"], p["p"], p["S_opt"], p["tie_breaking"]) != (5, .03, 100, "protector-priority"):
        raise ValueError("Reference scientific conditions changed")
    by_id = {s["scenario_id"]: s for s in d["scenarios"]}
    scenarios = [by_id[s] for s in request["scenario_ids"]]
    profiles = [next(s for s in d["profiles"] if s["profile_id"] == key) for key in request["profile_ids"]]
    preflight = computational_preflight(p, profiles, scenarios, 3, d["rates"], p["design_budget"])
    preflight["runtime_overhead_allowance_seconds"] = request["runtime_overhead_allowance_seconds"]
    preflight["projected_seconds_including_overhead"] = preflight["rate_projection_seconds_with_safety"]+request["runtime_overhead_allowance_seconds"]
    if preflight["projected_seconds_including_overhead"] > p["design_budget"]["max_projected_seconds"]:
        preflight["budget_reasons"].append("overhead_inclusive_projection_exceeds_budget")
    if {v["dataset"] for v in probes} != set(p["datasets"]):
        raise ValueError("Missing graph memory probes")
    # Forecast includes imports/graph copies, plus explicit 256 MiB headroom.
    memory_projection = 2*max(v["graph_and_copy_peak_RSS_bytes"] for v in probes)+256*1024**2
    if memory_projection > request["worker_RSS_limit_bytes"]:
        preflight["budget_reasons"].append("projected_worker_RSS_exceeds_limit")
    preflight["memory"] = {"probes": probes, "projected_worker_RSS_bytes": memory_projection,
                           "worker_RSS_limit_bytes": request["worker_RSS_limit_bytes"], "concurrent_workers": 1,
                           "forecast_is_hard_bound": False, "enforcement": "worker_ru_maxrss_watchdog_and_parent_heartbeat_guard"}
    preflight["within_declared_budget"] = not preflight["budget_reasons"]
    matrix = []
    width = p["random_seed_policy"]["block_width"]
    for scenario in scenarios:
        s_eval = p["S_eval_per_batch"][scenario["dataset"]]
        if max(p["S_opt"], s_eval*p["final_batches"]) > width//2:
            raise ValueError("MC schedule does not fit its reserved block")
        for repeat in range(3):
            # Counterbalance order, while seed IDs remain independent of execution order.
            order = profiles[repeat % 3:]+profiles[:repeat % 3]
            for profile in order:
                ordinal = request["profile_ids"].index(profile["profile_id"])
                opt_index = (scenario["scenario_index"]+1)*10000+ordinal*100+repeat
                final_index = scenario["scenario_index"]*100+repeat
                opt = make_experiment_seed_plan(request["master_seed"], opt_index, width)
                final = make_experiment_seed_plan(request["master_seed"], final_index, width)
                matrix.append({"run_id": f"{scenario['scenario_id']}_{profile['profile_id']}_r{repeat}",
                               "profile_id": profile["profile_id"], "scenario_id": scenario["scenario_id"], "scenario_index": scenario["scenario_index"],
                               "dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                               "k": p["k"], "p": p["p"], "tie_breaking": p["tie_breaking"], "S_opt": p["S_opt"],
                               "S_eval": s_eval, "final_batches": p["final_batches"], **profile["parameters"],
                               "repetition_index": repeat, "master_seed": request["master_seed"],
                               "optimization_run_index": opt_index, "final_run_index": final_index,
                               "GA_random_seed": opt.ga_random_seed,
                               "GA_operators_seed": make_seed_plan(opt.ga_random_seed, p["S_opt"], opt.optimization_base_random_seed).operators_seed,
                               "optimization_base_random_seed": opt.optimization_base_random_seed,
                               "optimization_seed_stop_exclusive": opt.optimization_base_random_seed+p["S_opt"],
                               "final_batch_seeds": [final.final_base_random_seed+b*s_eval for b in range(p["final_batches"])],
                               "final_seed_stop_exclusive": final.final_base_random_seed+p["final_batches"]*s_eval})
    pairs = []
    for scenario in scenarios:
        for repeat in range(3):
            rows = [r for r in matrix if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat]
            ref = next(r for r in rows if r["profile_id"] == "reference")
            for alt in [r for r in rows if r["profile_id"] != "reference"]:
                validate_confirmation_pair(ref, alt)
                pairs.append({"dataset": scenario["dataset"], "scenario_id": scenario["scenario_id"], "repetition_index": repeat,
                              "reference_run_id": ref["run_id"], "alternative_run_id": alt["run_id"]})
    reservations, reserved_schedule = reserve_main_scenarios(p, request, d["scenarios"])
    source_controls = json.loads((PROJECT_ROOT/"docs/pilot_2_calibration/control_summary.json").read_text())
    evidence = [r for r in source_controls if r["scenario_id"] in request["scenario_ids"] and r["p"] == p["p"]]
    return {"request": request, "protocol": p, "profiles": profiles, "scenarios": scenarios, "matrix": matrix, "pairs": pairs,
            "preflight": preflight, "rates": d["rates"], "scenario_control_evidence": evidence,
            "main_reservations": reservations, "reserved_main_schedule": reserved_schedule,
            "old_scenarios": d["scenarios"], "source_manifest_sha256": d["manifest_sha256"],
            "source_reachability_sha256": sha256_file(PROJECT_ROOT/"docs/pilot_2_calibration/reachable_nodes.csv")}


def export_plan(plan: dict, destination: Path) -> None:
    """Export reviewable design/seed reservations before any optimizer runs."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (("config", plan["request"]), ("preflight", plan["preflight"]), ("matrix", plan["matrix"]),
                        ("profiles", plan["profiles"]), ("scenarios", plan["scenarios"]), ("comparisons", plan["pairs"]),
                        ("scenario_control_evidence", plan["scenario_control_evidence"]), ("reserved_main_scenarios", plan["main_reservations"]),
                        ("reserved_main_schedule", plan["reserved_main_schedule"]), ("old_scenario_usage", plan["old_scenarios"]),
                        ("analysis_policy", plan["request"]["analysis_policy"]), ("source_rate_evidence", plan["rates"])):
        atomic_json(destination/f"{name}.json", value)
        if isinstance(value, list):
            write_csv(destination/f"{name}.csv", value)


def confirmation_worker(job_path: Path) -> int:
    """Reuse V2's exact GA/final bridge; add resource metadata only."""
    job = json.loads(job_path.read_text())
    path = Path(job["result_path"])
    with memory_guard(job.get("RSS_limit_bytes", 2*1024**3), Path(job.get("memory_path", path.with_suffix(".memory.json"))), job.get("memory_poll_seconds", .5)):
        bridge_path = path.with_suffix(".bridge.json")
        bridge_job = job_path.with_suffix(".bridge.json")
        atomic_json(bridge_job, {**job, "result_path": str(bridge_path)})
        verified_worker(bridge_job)
        result = json.loads(bridge_path.read_text())
        result["worker_peak_RSS_bytes"] = peak_rss_bytes()
        atomic_json(path, result)
        bridge_path.unlink()
        bridge_job.unlink()
    return 0


@contextmanager
def memory_guard(limit: int, heartbeat: Path, interval: float):
    """Monitor this process's peak RSS without process-list permissions.

    A daemon watchdog does not consume the optimizer's RNG. Exceeding the cap
    exits with status86 before a successful worker result can be accepted.
    """
    stop = Event()
    def observe():
        value = peak_rss_bytes()
        atomic_json(heartbeat, {"peak_RSS_bytes": value})
        if value > limit:
            os._exit(86)
    def watch():
        while not stop.wait(interval):
            observe()
    observe()
    thread = Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        observe()


def bounded_child(command: list[str], log_path: Path, timeout: float, rss_limit: int, poll: float, memory_path: Path) -> dict:
    """Parent wall limit plus RSS heartbeat checks; no process-list access."""
    started = perf_counter()
    maximum = 0
    reason = None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        child = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:
                remaining = timeout-(perf_counter()-started)
                if remaining <= 0:
                    reason = "worker_timeout"
                    child.kill()
                    break
                if memory_path.exists():
                    maximum = max(maximum, json.loads(memory_path.read_text())["peak_RSS_bytes"])
                if maximum > rss_limit:
                    reason = "worker_RSS_limit"
                    child.kill()
                    break
                try:
                    child.wait(timeout=min(poll, max(.001, remaining)))
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if child.poll() is None:
                child.kill()
            code = child.wait()
    if memory_path.exists():
        maximum = max(maximum, json.loads(memory_path.read_text())["peak_RSS_bytes"])
    if code == 86:
        reason = "worker_RSS_limit"
    elif code == 0 and not memory_path.exists():
        reason = "RSS_monitor_missing"
    return {"returncode": code, "reason": reason, "parent_sampled_peak_RSS_bytes": maximum,
            "measured_wall_seconds": perf_counter()-started}


def work_schedule(plan: dict) -> list[dict]:
    """27 GA/final units, then controls shared once per scenario/repeat/batch."""
    work = []
    for row in plan["matrix"]:
        upper = ga_evaluation_upper_bound({k: row[k] for k in GA_KEYS})*row["S_opt"]+row["S_eval"]*row["final_batches"]
        work.append({"work_id": row["run_id"], "kind": "GA", "row": row, "CIC_upper": upper})
    for scenario in plan["scenarios"]:
        for repeat in range(3):
            row = next(r for r in plan["matrix"] if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat and r["profile_id"] == "reference")
            for batch, seed in enumerate(row["final_batch_seeds"]):
                work.append({"work_id": f"control_{scenario['scenario_id']}_r{repeat}_b{batch}", "kind": "control", "row": row,
                             "batch": batch, "base_seed": seed, "CIC_upper": row["S_eval"]})
    return work


def execute(plan: dict, root: Path) -> dict:
    """Resume a frozen plan, guarding cumulative time, simulations and memory."""
    if not plan["preflight"]["within_declared_budget"]:
        return {"status": "stopped_at_preflight", "completed": {}}
    if root.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Do not write in data")
    root.mkdir(parents=True, exist_ok=True)
    protected = protected_snapshot()
    identity = fingerprint({"plan": plan, "protected": protected, "engine": sha256_file(Path(__file__)),
                            "reused_worker": sha256_file(PROJECT_ROOT/"experiments/reduced_screen_v2.py")})
    checkpoint = root/"checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["fingerprint"] != identity:
            raise ValueError("Code/data/config changed since checkpoint")
        reconcile_pending(state)
        for key, path in state["completed"].items():
            if not Path(path).exists() or sha256_file(Path(path)) != state["result_sha256"][key]:
                raise ValueError("Completed result changed")
    else:
        if any(root.iterdir()):
            raise ValueError("Output exists without checkpoint")
        state = {"fingerprint": identity, "started_utc": datetime.now(timezone.utc).isoformat(), "pending": None,
                 "completed": {}, "attempts": [], "charged_CIC": 0, "active_runtime_seconds": 0.0}
        atomic_json(root/"frozen_plan.json", plan)
        atomic_json(root/"integrity_before.json", protected)
        atomic_json(root/"metadata.json", environment_metadata())
    atomic_json(checkpoint, state)
    started, carried = perf_counter(), state["active_runtime_seconds"]
    work = work_schedule(plan)
    budget = plan["protocol"]["design_budget"]
    for unit in work:
        if unit["work_id"] in state["completed"]:
            continue
        remaining = budget["max_projected_seconds"]-carried-(perf_counter()-started)
        if remaining <= 0 or state["charged_CIC"]+unit["CIC_upper"] > budget["max_cic_simulations"]:
            state["stop_reason"] = "cumulative_runtime_or_CIC_limit"
            break
        attempt = sum(a["work_id"] == unit["work_id"] for a in state["attempts"])
        result_path = root/"runs"/f"{unit['work_id']}_attempt{attempt}.json"
        memory_path = result_path.with_suffix(".memory.json")
        job = {**unit, "result_path": str(result_path.resolve()), "fingerprint": fingerprint({"identity": identity, "unit": unit}),
               "RSS_limit_bytes": plan["request"]["worker_RSS_limit_bytes"], "memory_poll_seconds": plan["request"]["memory_poll_seconds"],
               "memory_path": str(memory_path.resolve())}
        job_path = root/"jobs"/f"{unit['work_id']}_attempt{attempt}.json"
        atomic_json(job_path, job)
        state["pending"] = {k: job[k] for k in ("work_id", "kind", "CIC_upper", "result_path", "fingerprint")}
        state["pending"]["timeout_seconds"] = min(remaining, plan["request"]["worker_timeout_seconds"])
        atomic_json(checkpoint, state)
        measured = bounded_child([sys.executable, "-B", "-m", "experiments.cross_scenario_ga_confirmation", "--worker", str(job_path)],
                                 root/"logs"/f"{unit['work_id']}_attempt{attempt}.txt", state["pending"]["timeout_seconds"],
                                 plan["request"]["worker_RSS_limit_bytes"], plan["request"]["memory_poll_seconds"], memory_path)
        state["pending"].update(measured)
        # A result is valid only if the wrapper finished successfully, including memory metadata.
        if measured["returncode"] or measured["reason"]:
            if result_path.exists():
                result_path.replace(result_path.with_suffix(".unaccepted.json"))
        reconcile_pending(state)
        atomic_json(checkpoint, state)
        print(f"{unit['work_id']}: {state['attempts'][-1]['status']}; {len(state['completed'])}/{len(work)} units; active {state['active_runtime_seconds']:.2f}s; sampled RSS {measured['parent_sampled_peak_RSS_bytes']/1024**2:.1f} MiB", flush=True)
        if state["attempts"][-1]["status"] != "completed":
            state["stop_reason"] = measured["reason"] or "worker_failed"
            break
    workers = state["active_runtime_seconds"]-carried
    elapsed = perf_counter()-started
    state["parent_overhead_seconds"] = state.get("parent_overhead_seconds", 0.0)+max(0, elapsed-workers)
    state["active_runtime_seconds"] = carried+elapsed
    after = protected_snapshot()
    atomic_json(root/"integrity_after.json", {"before": protected, "after": after, "unchanged": protected == after})
    if protected != after:
        raise RuntimeError("Protected data/core changed")
    state["status"] = "completed" if len(state["completed"]) == len(work) else "incomplete"
    if state["status"] == "completed":
        state.pop("stop_reason", None)
    atomic_json(checkpoint, state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=PROJECT_ROOT/"experiments/configs/cross_scenario_ga_confirmation.json")
    parser.add_argument("--phase", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--memory-probe", choices=("email-Eu-core", "ego-Facebook", "Wiki-Vote"))
    args = parser.parse_args(argv)
    if args.worker:
        return confirmation_worker(args.worker)
    if args.memory_probe:
        print(json.dumps(memory_probe(args.memory_probe)))
        return 0
    request = json.loads(args.request.read_text())
    destination = PROJECT_ROOT/request["export_directory"]
    if (destination/"memory_probes.json").exists():
        probes = json.loads((destination/"memory_probes.json").read_text())
    else:
        probes = []
        for dataset in ("email-Eu-core", "ego-Facebook", "Wiki-Vote"):
            result = subprocess.run([sys.executable, "-B", "-m", "experiments.cross_scenario_ga_confirmation", "--memory-probe", dataset],
                                    cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30, check=True)
            probes.append(json.loads(result.stdout))
        atomic_json(destination/"memory_probes.json", probes)
    plan = build_plan(request, probes)
    export_plan(plan, destination)
    print(json.dumps({k: v for k, v in plan["preflight"].items() if k != "rows"}, indent=2), flush=True)
    if args.phase == "run":
        state = execute(plan, PROJECT_ROOT/request["output_directory"])
        print(json.dumps({k: v for k, v in state.items() if k not in ("completed", "attempts", "result_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
