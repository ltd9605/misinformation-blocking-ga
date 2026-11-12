"""Confirmed four-run main adapter: verified selection, sealed P, two MC batches.

Checkpoint each selection/batch. No final call is allowed before all selections
have completed and their hashes are sealed. No core algorithm is reimplemented.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

import networkx as nx

from experiments.cross_scenario_ga_confirmation import bounded_child, memory_guard, peak_rss_bytes
from experiments.design_main_experiments import METHODS, build_plan as build_design, export_plan as export_design, grouped_preflight
from experiments.pilot_protocol_validation import write_csv
from experiments.reduced_screen_v2 import atomic_json, fingerprint, protected_snapshot, reconcile_pending
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic
from src.experiments.calibration import observation_summary
from src.experiments.metadata import environment_metadata
from src.experiments.runner import _plain, _select, preflight as selection_preflight
from src.experiments.seeds import make_experiment_seed_plan


def load_main_plan(request: dict) -> dict:
    """Only the explicitly approved change from five to four may alter v1."""
    previous = json.loads((PROJECT_ROOT/"experiments/configs/main_experiments_protocol.json").read_text())
    changed = {"protocol_version", "purpose", "execution_authorized", "design_confirmed", "repeats_confirmed",
               "proposed_independent_runs", "repeat_rationale", "budget_status", "output_directory",
               "execution_output_directory", "results_export_directory", "supersedes"}
    if set(request)-set(previous)-changed or any(request.get(k) != v for k, v in previous.items() if k not in changed):
        raise ValueError("Change outside the approved four-run revision")
    if request["proposed_independent_runs"] != 4 or not all(request[k] is True for k in ("execution_authorized", "design_confirmed", "repeats_confirmed")):
        raise ValueError("Require the user-confirmed four-run main protocol")
    planning = deepcopy(request)
    planning.update(execution_authorized=False, design_confirmed=False)
    plan = build_design(planning)
    plan["request"] = deepcopy(request)
    for row in plan["matrix"]:
        if row["method_eligible"]:
            row.update(admission_status="admitted" if plan["preflight"]["within_declared_budget"] else "blocked_global_preflight",
                       execution_status="planned", reason=None if plan["preflight"]["within_declared_budget"] else "; ".join(plan["preflight"]["admission_reasons"]))
    plan["seed_separation_audit"] = seed_separation_audit(plan)
    plan["execution_gate"] = "authorized_by_current_user_if_preflight_and_adapter_tests_pass"
    confirmations = {"main_design_confirmation": "confirmed_by_current_user", "repeats": "confirmed_four",
                     "main_budget": "confirmed_10800_seconds", "main_adapter": "implemented_validated_before_execution"}
    for condition in plan["unconfirmed_conditions"]:
        if condition["id"] in confirmations:
            condition.update(status=confirmations[condition["id"]], requirement="resolved by four-run approval and tested adapter; original five-run artifacts retained")
    return plan


def seed_separation_audit(plan: dict) -> dict:
    """Verify main intervals against recorded calibration/screen/confirmation intervals."""
    historical = []
    inputs = set()
    def interval(base, size, source):
        if size:
            historical.append((base, base+size, source))
    for file in ("docs/pilot_2_calibration/optimization_results.json", "docs/pilot_protocol_validation/results.json"):
        for r in json.loads((PROJECT_ROOT/file).read_text()):
            if r["optimization_cic_simulations"]:
                interval(r["optimization_base_random_seed"], r["S_opt"], file)
            if r["final_cic_simulations"]:
                interval(r["final_base_random_seed"], r["S_eval"], file)
    for file in ("docs/pilot_2_calibration/accuracy_statistics.json", "docs/pilot_2_calibration/control_batches.csv"):
        if file.endswith(".csv"):
            import csv
            with (PROJECT_ROOT/file).open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            for r in rows:
                if r["status"] == "completed":
                    interval(int(r["base_random_seed"]), int(r["actual_cic_simulations"]), file)
        else:
            for r in json.loads((PROJECT_ROOT/file).read_text()):
                interval(r["base_random_seed"], r["S_eval"], file)
    for campaign in ("milestone_7_reduced_screen_v2", "cross_scenario_ga_confirmation"):
        file = f"docs/{campaign}/run_results.json"
        for r in json.loads((PROJECT_ROOT/file).read_text()):
            interval(r["optimization_base_random_seed"], r["S_opt"], file)
            interval(r["final_batch_seeds"][0], r["final_simulations"], file)
            inputs.update((r["GA_random_seed"], r["GA_operators_seed"]))
    file = "docs/experiment_protocol_v1/pilot/results.json"
    for r in json.loads((PROJECT_ROOT/file).read_text()):
        interval(r["seeds"]["optimization_base_seed"], r["S_opt"], file)
        interval(r["seeds"]["final_base_seed"], r["total_final_simulations"], file)
        inputs.add(r["seeds"]["operators_input_seed"])
    rows = [r for r in plan["matrix"] if r["algorithm"] == "genetic_algorithm"]
    for a in rows:
        current = [(a["optimization_base_random_seed"], a["optimization_seed_stop_exclusive"]),
                   (a["final_batch_seeds"][0], a["final_seed_stop_exclusive"])]
        if any(a[k] in inputs for k in ("GA_random_seed", "GA_operators_seed", "random_selection_seed")):
            raise ValueError("Main selection RNG collides with a prior recorded RNG")
        for start, stop in current:
            if any(start < old_stop and old_start < stop for old_start, old_stop, _ in historical):
                raise ValueError("Main CIC schedule overlaps recorded previous evaluations")
        for b in rows:
            if a["optimization_base_random_seed"] < b["final_seed_stop_exclusive"] and b["final_batch_seeds"][0] < a["optimization_seed_stop_exclusive"]:
                raise ValueError("Main optimization/final overlap")
    if len({r["optimization_base_random_seed"] for r in rows}) != 24:
        raise ValueError("Expected24 independent comparison blocks")
    return {"passed": True, "main_comparison_blocks": 24, "historical_CIC_intervals_checked": len(historical),
            "recorded_selection_RNGs_checked": len(inputs), "main_master": plan["request"]["master_seed"],
            "optimization_final_disjoint": True, "no_calibration_screen_confirmation_overlap": True,
            "same_final_schedule_within_comparison": True,
            "scope": "recorded evaluator intervals plus disjoint Cantor/master namespace; legacy SHA fitness seeds occupy64-bit space whereas main blocks exceed64-bit"}


def selection_settings(request: dict, row: dict) -> dict:
    """Translate the frozen protocol to the unchanged dispatcher's settings."""
    return {"k": row["k"], "p": row["p"], "S_opt": row["S_opt"], "tie_breaking": row["tie_breaking"],
            "algorithms": [row["algorithm"]], "ga_parameters": request["GA"], "pagerank_parameters": request["pagerank"],
            "candidate_restriction": {"method": "degree", "size": request["candidate_restricted_greedy"]["pool_size"]},
            "limits": {"max_optimization_evaluations": 100, "max_optimization_cic_simulations": 100*row["S_opt"],
                       "max_full_greedy_evaluations": request["full_greedy_limits"]["max_evaluator_calls"],
                       "max_full_greedy_cic_simulations": request["full_greedy_limits"]["max_cic_simulations"]}}


def select_on_graph(graph: nx.Graph, request: dict, row: dict) -> dict:
    """Use Milestone6's exact dispatcher once; retain its full audit payload."""
    if row["algorithm"] not in METHODS:
        raise ValueError("Method not admitted in the main matrix")
    rumor = tuple(row["rumor_seeds"])
    if set(rumor).difference(graph) or row["k"] > len(graph)-len(rumor):
        raise ValueError("Invalid graph/R/budget")
    c = selection_settings(request, row)
    selection_preflight(graph, rumor, c)
    seeds = make_experiment_seed_plan(row["master_seed"], row["seed_run_index"], request["seed_block_width"])
    if seeds.optimization_base_random_seed != row["optimization_base_random_seed"] or seeds.ga_random_seed != row["GA_random_seed"]:
        raise ValueError("Selection seed schedule changed")
    protector, timing, details, convergence = _select(graph, rumor, c, row["algorithm"], seeds)
    return {"row": row, "protector_seeds": sorted(protector), "timing": timing, "selection_details": details,
            "convergence": convergence, "evaluator_calls": timing["optimization_evaluation_count"],
            "CIC_simulations": timing["optimization_cic_simulations"]}


def evaluate_on_graph(graph: nx.Graph, row: dict, protector: list[int], batch: int) -> dict:
    """Evaluate the already sealed P; no selection or fitness reuse is possible."""
    expected_size = 0 if row["algorithm"] == "no_intervention" else row["k"]
    if len(protector) != len(set(protector)) or len(protector) != expected_size or set(protector)&set(row["rumor_seeds"]) or set(protector).difference(graph):
        raise ValueError("Sealed protector set violates the frozen problem")
    seed = row["final_batch_seeds"][batch]
    started = perf_counter()
    estimate = evaluate_cic(graph, row["rumor_seeds"], protector, row["p"], row["S_eval_per_batch"],
                            base_random_seed=seed, tie_breaking=row["tie_breaking"])
    wall = perf_counter()-started
    raw = {key: [getattr(r, key) for r in estimate.raw_results] for key in ("rumor_count", "protector_count", "inactive_count", "steps")}
    return {"row": row, "protector_seeds": protector, "batch": batch, "base_random_seed": seed,
            "final_evaluation_runtime_seconds": wall, "core_MC_runtime_seconds": estimate.runtime_seconds,
            "statistics": observation_summary(raw["rumor_count"], len(graph)), "raw_counts": raw,
            "mean_protector_count": estimate.mean_protector_count, "mean_inactive_count": estimate.mean_inactive_count,
            "evaluator_calls": 1, "CIC_simulations": row["S_eval_per_batch"]}


def worker(job_path: Path) -> int:
    """One bounded selection or final-batch process, publishing one atomic result."""
    started = perf_counter()
    job = json.loads(job_path.read_text())
    row, request = job["row"], job["request"]
    with memory_guard(job["RSS_limit_bytes"], Path(job["memory_path"]), request["resource_limits"]["RSS_sampling_seconds"]):
        t0 = perf_counter()
        graph = load_processed_graph(PROJECT_ROOT/"data/processed"/row["dataset"])
        loading = perf_counter()-t0
        before = deepcopy(graph)
        nx.freeze(graph)
        if job["kind"] == "selection":
            payload = select_on_graph(graph, request, row)
        else:
            path = Path(job["selection_path"])
            if sha256_file(path) != job["selection_sha256"]:
                raise ValueError("Sealed P changed")
            selection = json.loads(path.read_text())
            if selection["row"] != row:
                raise ValueError("Final evaluation context differs from selection")
            payload = evaluate_on_graph(graph, row, selection["protector_seeds"], job["batch"])
            payload["selection_sha256"] = job["selection_sha256"]
        if not nx.utils.graphs_equal(graph, before):
            raise RuntimeError("Graph changed")
        payload.update(kind=job["kind"], work_id=job["work_id"], graph_nodes=len(graph), graph_edges=graph.number_of_edges(),
                       graph_loading_seconds=loading, graph_unchanged=True, worker_peak_RSS_bytes=peak_rss_bytes(),
                       worker_runtime_seconds=perf_counter()-started, job_fingerprint=job["fingerprint"], status="completed")
        atomic_json(Path(job["result_path"]), payload)
    return 0


def work_schedule(plan: dict) -> list[dict]:
    """All144 selections precede all288 final batches; Full Greedy excluded."""
    rows = [r for r in plan["matrix"] if r["method_eligible"]]
    ordered = []
    for scenario in plan["scenarios"]:
        for repeat in range(plan["request"]["proposed_independent_runs"]):
            block = [r for r in rows if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat]
            shift = (scenario["scenario_index"]+repeat) % len(METHODS)
            order = METHODS[shift:]+METHODS[:shift]
            ordered.extend(next(r for r in block if r["algorithm"] == method) for method in order)
    selections = [{"work_id": f"select_{r['unit_id']}", "kind": "selection", "row": r,
                   "CIC_upper": r["budgeted_optimization_CIC_upper"]} for r in ordered]
    finals = [{"work_id": f"final_{r['unit_id']}_b{batch}", "kind": "final", "row": r, "batch": batch,
               "CIC_upper": r["S_eval_per_batch"]} for r in ordered for batch in range(r["final_batches"])]
    return selections+finals


def seal_selections(plan: dict, root: Path, state: dict) -> dict:
    """No final evaluator may run unless every planned P is present and unchanged."""
    sealed = {}
    for row in [r for r in plan["matrix"] if r["method_eligible"]]:
        key = f"select_{row['unit_id']}"
        if key not in state["completed"]:
            raise ValueError("Final evaluation blocked: incomplete selection barrier")
        path = Path(state["completed"][key])
        if sha256_file(path) != state["result_sha256"][key]:
            raise ValueError("Selection artifact changed before barrier")
        value = json.loads(path.read_text())
        if value["row"] != row:
            raise ValueError("Frozen comparison context changed")
        sealed[row["unit_id"]] = {"selection_path": str(path), "selection_sha256": state["result_sha256"][key],
                                 "protector_seeds": value["protector_seeds"]}
    path = root/"selection_barrier.json"
    payload = {"all_P_sealed_before_any_final": True, "selections": sealed}
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError("Selection barrier no longer matches its frozen P")
    else:
        atomic_json(path, payload)
    return payload


def execute(plan: dict, root: Path) -> dict:
    """Run/resume the confirmed matrix within cumulative time/CIC/RSS limits."""
    q = plan["request"]
    if not q["execution_authorized"] or not q["design_confirmed"] or not plan["seed_separation_audit"]["passed"]:
        raise ValueError("Main protocol is not authorized/seed-safe")
    if not plan["preflight"]["within_declared_budget"]:
        return {"status": "stopped_at_preflight", "completed": {}}
    if root.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Do not write in data")
    root.mkdir(parents=True, exist_ok=True)
    protected = protected_snapshot()
    identity = fingerprint({"plan": plan, "protected": protected, "engine": sha256_file(Path(__file__))})
    checkpoint = root/"checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["fingerprint"] != identity:
            raise ValueError("Code/data/config changed since main checkpoint")
        reconcile_pending(state)
        for work_id, path in state["completed"].items():
            if not Path(path).exists() or sha256_file(Path(path)) != state["result_sha256"][work_id]:
                raise ValueError("Completed main artifact changed")
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
    budget, limits = q["admission_budget"], q["resource_limits"]
    schedule = work_schedule(plan)
    barrier = None
    for unit in schedule:
        if unit["work_id"] in state["completed"]:
            continue
        if peak_rss_bytes() > limits["parent_RSS_allowance_bytes"]:
            state["stop_reason"] = "parent_RSS_limit"
            break
        if unit["kind"] == "final" and barrier is None:
            barrier = seal_selections(plan, root, state)
        remaining = budget["max_projected_seconds"]-carried-(perf_counter()-started)
        if remaining <= 0 or state["charged_CIC"]+unit["CIC_upper"] > budget["max_cic_simulations"]:
            state["stop_reason"] = "cumulative_main_runtime_or_CIC_limit"
            break
        attempt = sum(a["work_id"] == unit["work_id"] for a in state["attempts"])
        result_path = root/"units"/f"{unit['work_id']}_attempt{attempt}.json"
        memory_path = result_path.with_suffix(".memory.json")
        job = {**unit, "request": q, "result_path": str(result_path.resolve()), "memory_path": str(memory_path.resolve()),
               "RSS_limit_bytes": limits["worker_RSS_bytes"]}
        if unit["kind"] == "final":
            job.update({k: v for k, v in barrier["selections"][unit["row"]["unit_id"]].items() if k != "protector_seeds"})
        job["fingerprint"] = fingerprint({"identity": identity, "unit": unit,
                                          "selection_sha256": job.get("selection_sha256")})
        job_path = root/"jobs"/f"{unit['work_id']}_attempt{attempt}.json"
        atomic_json(job_path, job)
        cap = limits["selection_timeout_seconds"] if unit["kind"] == "selection" else limits["final_batch_timeout_seconds"]
        state["pending"] = {k: job[k] for k in ("work_id", "kind", "CIC_upper", "result_path", "fingerprint")}
        state["pending"]["timeout_seconds"] = min(remaining, cap)
        atomic_json(checkpoint, state)
        measured = bounded_child([sys.executable, "-B", "-m", "experiments.main_experiments", "--worker", str(job_path)],
                                 root/"logs"/f"{unit['work_id']}_attempt{attempt}.txt", state["pending"]["timeout_seconds"],
                                 limits["worker_RSS_bytes"], limits["RSS_sampling_seconds"], memory_path)
        state["pending"].update(measured)
        if (measured["returncode"] or measured["reason"]) and result_path.exists():
            result_path.replace(result_path.with_suffix(".unaccepted.json"))
        reconcile_pending(state)
        atomic_json(checkpoint, state)
        print(f"{unit['work_id']}: {state['attempts'][-1]['status']}; {len(state['completed'])}/{len(schedule)} units; active {state['active_runtime_seconds']:.2f}s", flush=True)
        if state["attempts"][-1]["status"] != "completed":
            state["stop_reason"] = measured["reason"] or "worker_failed"
            break
    accounted = state["active_runtime_seconds"]-carried
    elapsed = perf_counter()-started
    state["parent_overhead_seconds"] = state.get("parent_overhead_seconds", 0.0)+max(0, elapsed-accounted)
    state["active_runtime_seconds"] = carried+elapsed
    after = protected_snapshot()
    atomic_json(root/"integrity_after.json", {"before": protected, "after": after, "unchanged": protected == after})
    if protected != after:
        raise RuntimeError("Main changed protected core/data")
    state["status"] = "completed" if len(state["completed"]) == len(schedule) else "incomplete"
    if state["status"] == "completed":
        state.pop("stop_reason", None)
    atomic_json(checkpoint, state)
    return state


def export_protocol(plan: dict, destination: Path) -> None:
    """New v2 artifacts only; the five-run design is never overwritten."""
    if destination.exists():
        frozen = json.loads((destination/"frozen_main_plan.json").read_text())
        if frozen != plan:
            raise ValueError("V2 design directory already contains a different freeze")
        return
    export_design(plan, destination)
    atomic_json(destination/"frozen_main_plan.json", plan)
    atomic_json(destination/"seed_separation_audit.json", plan["seed_separation_audit"])
    atomic_json(destination/"summary.json", {"status": "admitted" if plan["preflight"]["within_declared_budget"] else "stopped_at_preflight",
                "design_confirmed": True, "execution_authorized": True, "independent_runs": 4,
                "primary_result_rows": 144, "Full_Greedy_rows_skipped": 24,
                "previous_five_run_protocol_preserved": True, "preflight": {k: v for k, v in plan["preflight"].items() if k != "rows"}})
    tables = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {r['optimization_evaluator_calls_upper']+r['final_evaluator_calls']} | {r['optimization_CIC_upper']+r['final_CIC']} | {r['planning_ceiling_seconds_with_safety_excluding_shared_overhead']:.2f} |" for r in grouped_preflight(plan, "scenario_id"))
    p = plan["preflight"]
    (PROJECT_ROOT/"MAIN_EXPERIMENTS_PROTOCOL_V2.md").write_text(f"""# Main Experiments Protocol V2 — Four Independent Runs

User xác nhận ngày12/11/2026: giảm repetitions5→4/scenario để giữ cap10.800s.
Đây là revision trước bất kỳ main observation nào, không phải adaptive stopping.
Giữ nguyên [protocol5runs](MAIN_EXPERIMENTS_PROTOCOL.md) và JSON/artifacts cũ.

## Frozen design

6R nguyên trạng: email485/374,Facebook714/2733,Wiki1961/1795;3 processed graphs,
k5/p.03/protector-priority. GA N10/G10/crossover.8/mutation.1/tournament3/elite1/
cacheTrue/S_opt100. Candidate-Restricted pool10 theo out-degree/degree ngoàiR;
Degree cùng ranking rule;PageRank alpha.85/tol1e-12/max_iter1000;Random có seed.
S_eval6000/batch email,2500/batch Facebook/Wiki,B2, cùng final schedules giữa6
methods mỗi comparison. 6R×4×6=144 result rows. Full Greedy24 rows skipped theo
calls100/CIC2000, không thay tên Restricted. Không reselect R hoặc retune GA.

## Preflight

Selection upper3360 evaluator calls/336.000CIC; final288calls/1.056.000CIC,
gồm48 shared NI calls; tổng**3648calls/1.392.000CIC**. Projection theo đúng rate
evidence v1, không update bằng main results: **{p['projected_seconds_including_safety_and_overhead']:.3f}s**
(safety1.5+overhead300), headroom**{p['runtime_headroom_seconds']:.3f}s** so với10800.
Runtime là proxy, không là hard bound. RAM worker2GiB/parent512MiB/concurrency1,
selection timeout900s,final120s/batch, tất cả bị giới hạn bởi active budget còn lại.

| Dataset | R | Calls upper | CIC upper | Proxy safety1.5 s, chưa shared overhead |
|---|---|---:|---:|---:|
{tables}

## Seeds, checkpoints and analysis

Giữ main master2026111109,ordinal11..16,index=scenario_index*100+repeat0..3;
dùng4 trong10 slots đã reserve, không tiêu thụ6 slots còn lại. Optimization
100seed đầu block;final nửa sau với hai batch bases. GA/Greedy chia sẻ opt
schedule trong comparison; mọi method cùng final schedule. Kiểm tra interval
không trùng calibration/M7/confirmation và không giao opt/final, bảng JSON kèm.

Adapter mới gọi nguyên `_select()` Milestone6 và `evaluate_cic()`, không gọi
one-batch runner hai lần. Toàn bộ144P được checkpoint/hash và seal trước final.
288final batches checkpoint riêng, controls một lần/batch, raw counts giữ đủ.
Resume xác minh config/core/graph/P/seed hashes, bỏ qua completed units, charge
upper CIC/timeout cho unknown partial work; không reset budget. Runtime tách
selection/fitness-subset/final/loading/import/guard/export/total active.

Statistical policy v1 giữ nguyên:30scenario contrasts GA−5comparators +15
equal-weight within-dataset contrasts, approximate Bonferroni family45; nay
CI qua4 paired runs/bundles,df3. Không pool effects giữa datasets. Spread
reduction là1−ratio-of-means, không clip số âm; descriptive paired Fieller
sets có thể bounded/unbounded/disjoint. Dataset average của hai scenario
ratios dùng conservative sum của hai97.5%Fieller sets (descriptive95% coverage
xấp xỉ). Chưa có equivalence margin; CI chứa0 là chưa đủ bằng chứng, không
equivalence. Tách conditional MC variance, algorithm-run variability và
scenario heterogeneity; deterministic NI/Degree/PageRank không tạo thêm
selection randomness. n4 có uncertainty/power yếu hơn n5; không đổi repeats
hoặc lọc low/no-spread R sau outcomes. Training fitness chỉ diagnostic.

Các file: [configV2](experiments/configs/main_experiments_protocol_v2.json),
[matrixCSV](docs/main_experiments_protocol_v2/matrix.csv),
[preflightJSON](docs/main_experiments_protocol_v2/preflight.json),
[seed audit](docs/main_experiments_protocol_v2/seed_separation_audit.json).
Main results xuất riêng MAIN_EXPERIMENTS_RESULTS.md và docs/main_experiments_results.
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=PROJECT_ROOT/"experiments/configs/main_experiments_protocol_v2.json")
    parser.add_argument("--phase", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)
    q = json.loads(args.request.read_text())
    plan = load_main_plan(q)
    export_protocol(plan, PROJECT_ROOT/q["output_directory"])
    print(json.dumps({k: v for k, v in plan["preflight"].items() if k != "rows"}, indent=2), flush=True)
    if args.phase == "run":
        state = execute(plan, PROJECT_ROOT/q["execution_output_directory"])
        print(json.dumps({k: v for k, v in state.items() if k not in ("completed", "attempts", "result_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
