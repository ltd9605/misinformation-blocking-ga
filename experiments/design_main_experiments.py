"""Read-only main design freeze/preflight exporter; no experiment execution path.

No diffusion, Monte Carlo or protector selection API is called. Runtime records
are historical proxies, not measurements on the six reserved main scenarios.
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from math import isfinite, log1p
from pathlib import Path
import json

import networkx as nx

from experiments.cross_scenario_ga_confirmation import reserve_main_scenarios
from experiments.design_protocol_v1 import load_protocol
from experiments.pilot_protocol_validation import write_csv
from experiments.reduced_screen_v2 import atomic_json, fingerprint
from src.algorithms import estimate_greedy_cost, make_seed_plan
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.calibration import reachable_sizes
from src.experiments.seeds import make_experiment_seed_plan
from src.experiments.sensitivity import ga_evaluation_upper_bound


METHODS = ("no_intervention", "random", "degree", "pagerank", "candidate_restricted_greedy", "genetic_algorithm")


def read_json(relative: str) -> object:
    return json.loads((PROJECT_ROOT/relative).read_text(encoding="utf-8"))


def validate_request(request: dict) -> dict:
    """Reject drift of locked research settings and any execution authorization."""
    base = load_protocol(PROJECT_ROOT/request["source_protocol"])
    if request["execution_authorized"] or request["design_confirmed"]:
        raise ValueError("Planning CLI cannot authorize or execute main")
    if not request["GA_lock_confirmed_by_user"] or request["GA"] != base["reference_ga"]:
        raise ValueError("Locked GA changed")
    for key in ("k", "p", "tie_breaking", "S_opt", "S_eval_per_batch", "final_batches", "full_greedy_limits"):
        if request[key] != base[key]:
            raise ValueError(f"Locked reference condition changed: {key}")
    if tuple(request["primary_methods"]) != METHODS or request["conditional_method"] != "full_greedy":
        raise ValueError("Expected six primary methods and conditional Full Greedy")
    if request["candidate_restricted_greedy"] != {"pool_size": 10, "ranking": "out_degree_if_directed_else_degree", "tie_breaking": "ascending_actual_integer_node_id"}:
        raise ValueError("Restricted Greedy policy changed")
    if request["pagerank"] != read_json("experiments/configs/pilot_2_calibration.json")["pagerank_parameters"]:
        raise ValueError("Use the measured PageRank configuration")
    if type(request["proposed_independent_runs"]) is not int or not 2 <= request["proposed_independent_runs"] <= 10:
        raise ValueError("Propose 2..10 repetitions within reserved slots")
    for key, value in base["design_budget"].items():
        if request["admission_budget"][key] != value:
            raise ValueError("Do not silently raise admission limits or lower safety")
    if request["master_seed"] != 2026111109 or request["seed_block_width"] != base["random_seed_policy"]["block_width"]:
        raise ValueError("Preserve the main seed reservation")
    if request["admission_budget"]["overhead_allowance_seconds"] < 0 or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in request["resource_limits"].values()):
        raise ValueError("Invalid overhead/resource limits")
    policy = request["analysis_policy"]
    if policy["primary_CI_family_size"] != policy["scenario_effects"]+policy["within_dataset_equal_scenario_weight_effects"] or policy["primary_CI_family_size"] != 45:
        raise ValueError("Prespecify all 45 contrasts")
    if any(policy[k] for k in ("cross_dataset_effect_pooling", "training_fitness_as_final_metric", "GA_retuning_after_main_outcomes", "adaptive_R_filtering_or_repeat_changes")):
        raise ValueError("Forbidden adaptive or pooled analysis")
    if policy["comparators"] != list(METHODS[:-1]):
        raise ValueError("Comparison family changed")
    if policy["within_dataset_scenario_weights"] != [.5, .5] or policy["scenario_population_inference"]:
        raise ValueError("Preserve fixed equal-weight scenario summaries without population inference")
    return base


def historical_rates() -> tuple[list[dict], dict]:
    """Extract measured p=.03/k5 timings without reading algorithm quality.

    Only the largest S2500 accuracy prefix is included: nested smaller prefixes
    are not additional independent timings. Counts here are provenance records,
    not statistical sample sizes. For GA non-MC overhead use N10/G10 only.
    """
    records, hashes = [], {}
    def rows(path):
        hashes[path] = sha256_file(PROJECT_ROOT/path)
        return read_json(path)
    def add(dataset, rumor, algorithm, phase, seconds, units, source, index, S=None):
        if units <= 0 or seconds < 0 or not isfinite(seconds):
            raise ValueError("Invalid historical runtime")
        records.append({"dataset": dataset, "rumor_seeds": rumor, "algorithm": algorithm, "phase": phase,
                        "seconds_per_unit": seconds/units, "measured_seconds": seconds, "measured_units": units,
                        "S": S, "p": .03, "source": source, "source_row_index": index,
                        "observed_on_main_R": False})
    path = "docs/pilot_2_calibration/optimization_results.json"
    for i, r in enumerate(rows(path)):
        if r["p"] != .03 or r["phase"] == "smoke" or r["k"] != 5:
            continue
        d, rumor, a = r["dataset"], r["rumor_seeds"], r["algorithm"]
        if r["final_cic_simulations"]:
            add(d, rumor, a, "final", r["final_evaluation_runtime_seconds"], r["final_cic_simulations"], path, i, r["S_eval"])
        if r["optimization_cic_simulations"] and r["S_opt"] == 100:
            add(d, rumor, a, "optimization", r["optimization_evaluator_seconds"], r["optimization_cic_simulations"], path, i, 100)
        add(d, rumor, a, "selection_non_MC", max(0, r["selection_runtime_seconds"]-r["optimization_evaluator_seconds"]), 1, path, i)
    path = "docs/pilot_2_calibration/accuracy_statistics.json"
    for i, r in enumerate(rows(path)):
        if r["p"] == .03 and r["S_eval"] == 2500:
            add(r["dataset"], r["rumor_seeds"], r["algorithm"], "final", r["runtime_prefix_MC_seconds"], r["S_eval"], path, i, r["S_eval"])
    # Larger measured final S and two additional R per directed dataset.
    for campaign in ("milestone_7_reduced_screen_v2", "cross_scenario_ga_confirmation"):
        path = f"docs/{campaign}/run_results.json"
        for i, r in enumerate(rows(path)):
            add(r["dataset"], r["rumor_seeds"], "genetic_algorithm", "optimization", r["fitness_MC_runtime_seconds"], r["optimization_CIC_simulations"], path, i, r["S_opt"])
            if r["profile_id"] == "reference":
                add(r["dataset"], r["rumor_seeds"], "genetic_algorithm", "selection_non_MC", r["selection_non_MC_seconds"], 1, path, i)
        path = f"docs/{campaign}/final_batches.json"
        run_lookup = {r["run_id"]: r for r in read_json(f"docs/{campaign}/run_results.json")}
        for i, r in enumerate(rows(path)):
            parent = run_lookup[r["run_id"]]
            add(parent["dataset"], parent["rumor_seeds"], "genetic_algorithm", "final", r["runtime_seconds"], r["S"], path, i, r["S"])
        path = f"docs/{campaign}/control_results.json"
        for i, r in enumerate(rows(path)):
            add(r.get("dataset", "email-Eu-core"), r.get("rumor_seeds", [926]), "no_intervention", "final", r["runtime_seconds"], r["S"], path, i, r["S"])
    path = "docs/experiment_protocol_v1/pilot/results.json"
    for i, r in enumerate(rows(path)):
        add(r["dataset"], r["rumor_seeds"], "genetic_algorithm", "optimization", r["fitness_evaluator_seconds"], r["fitness_CIC_simulations"], path, i, r["S_opt"])
        if r["profile_id"] == "reference":
            add(r["dataset"], r["rumor_seeds"], "genetic_algorithm", "selection_non_MC", max(0, r["selection_seconds"]-r["fitness_evaluator_seconds"]), 1, path, i)
    for filename in ("final_batches", "controls"):
        path = f"docs/experiment_protocol_v1/pilot/{filename}.json"
        for i, r in enumerate(rows(path)):
            rumor = [926] if r["dataset"] == "email-Eu-core" else [1210]
            add(r["dataset"], rumor, "genetic_algorithm" if filename == "final_batches" else "no_intervention", "final", r["runtime_seconds"], r["S"], path, i, r["S"])
    return records, hashes


def topology_audit(request: dict, records: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    """Reproduce reserved sampling and audit exact topology without simulations."""
    protocol = load_protocol(PROJECT_ROOT/request["source_protocol"])
    original = read_json(protocol["scenario_manifest"])
    cross_request = read_json("experiments/configs/cross_scenario_ga_confirmation.json")
    expected, _ = reserve_main_scenarios(protocol, cross_request, original)
    reserved = read_json(request["scenario_reservation"])
    if reserved != expected:
        raise ValueError("Reserved R changed from its topology-only sampling policy")
    prior_validation = read_json("docs/pilot_protocol_validation/rumor_scenarios.json")
    previous = defaultdict(set)
    for r in original:
        previous[r["dataset"]].update(r["rumor_seeds"])
    for d, r in prior_validation.items():
        previous[d].update(r["rumor_seeds"])
    previous["email-Eu-core"].add(0)
    audited, descriptors, graph_info = [], {}, []
    for dataset in protocol["datasets"]:
        graph = load_processed_graph(PROJECT_ROOT/"data/processed"/dataset)
        reach = reachable_sizes(graph)
        degree = dict(graph.out_degree() if graph.is_directed() else graph.degree())
        weak = nx.weakly_connected_components(graph) if graph.is_directed() else nx.connected_components(graph)
        component_sizes = {v: len(c) for c in weak for v in c}
        strong = {v: len(c) for c in nx.strongly_connected_components(graph) for v in c} if graph.is_directed() else component_sizes
        historical_R = {v for r in records if r["dataset"] == dataset for v in r["rumor_seeds"]}
        for node in historical_R | {s["rumor_seeds"][0] for s in reserved if s["dataset"] == dataset}:
            descriptors[(dataset, node)] = {"propagation_degree": degree[node], "reachable_fraction": reach[node]/len(graph)}
        for s in [r for r in reserved if r["dataset"] == dataset]:
            node = s["rumor_seeds"][0]
            if node in previous[dataset] or node not in graph or reach[node] != s["reachable_count"]:
                raise ValueError("Reserved R collision or topology drift")
            p0 = (1-request["p"])**degree[node]
            audited.append({**s, "node_count": len(graph), "edge_count": graph.number_of_edges(), "directed": graph.is_directed(),
                            "propagation_degree": degree[node], "in_degree": graph.in_degree(node) if graph.is_directed() else None,
                            "degree_rank_fraction_strict_lower": sum(v < degree[node] for v in degree.values())/len(graph),
                            "degree_tie_count": sum(v == degree[node] for v in degree.values()),
                            "reachable_fraction_of_graph": reach[node]/len(graph), "reachable_excluding_seed": reach[node]-1,
                            "SCC_or_component_size": strong[node], "WCC_or_component_size": component_sizes[node],
                            "local_clustering": nx.clustering(graph, node),
                            "no_intervention_no_growth_probability_analytic": p0,
                            "expected_first_layer_no_intervention": request["p"]*degree[node],
                            "known_prior_R_ids": sorted(previous[dataset]), "prior_R_overlap": False,
                            "main_MC_observations_generated": 0, "measured_rumor_mean": None,
                            "retention_policy": "retain_even_if_no_spread_or_low_spread; never_filter_by_algorithm_outcomes"})
        graph_info.append({"dataset": dataset, "nodes": len(graph), "edges": graph.number_of_edges(),
                           "directed": graph.is_directed(), "maximum_reachable": max(reach.values())})
    return audited, descriptors, graph_info


def rate_proxy(dataset: str, node: int, algorithm: str, phase: str, records: list[dict], descriptors: dict) -> dict:
    """Nearest-topology nominal proxy plus whole-cohort timing envelope.

    Nearest degree/reachability is a transparent heuristic, not a fitted runtime
    model. Admission uses all-cohort max and a safety factor. Actual main-R
    runtime remains null; identical planning ceilings do not assert equal costs.
    """
    group = [r for r in records if (r["dataset"], r["algorithm"], r["phase"]) == (dataset, algorithm, phase)]
    if not group:
        raise ValueError(f"Missing measured runtime context: {dataset}/{algorithm}/{phase}")
    target = descriptors[(dataset, node)]
    def distance(source_node):
        ref = descriptors[(dataset, source_node)]
        return abs(log1p(target["propagation_degree"])-log1p(ref["propagation_degree"]))+abs(target["reachable_fraction"]-ref["reachable_fraction"])
    sources = sorted({r["rumor_seeds"][0] for r in group})
    nearest = min(sources, key=lambda n: (distance(n), n))
    return {"min_observed_rate": min(r["seconds_per_unit"] for r in group),
            "max_observed_rate": max(r["seconds_per_unit"] for r in group),
            "nearest_topology_proxy_rate": max(r["seconds_per_unit"] for r in group if r["rumor_seeds"] == [nearest]),
            "nearest_historical_R": [nearest], "topology_distance": distance(nearest),
            "observed_R_ids": sources, "provenance_record_count_not_independent_n": len(group),
            "observed_on_main_R": False, "main_R_actual_rate": None,
            "proxy_is_validated_causal_model": False}


def method_costs(request: dict, nodes: int) -> dict:
    """Exact Greedy work and cache-free GA upper counts; no optimization calls."""
    restricted = estimate_greedy_cost(request["candidate_restricted_greedy"]["pool_size"], request["k"], request["S_opt"])
    full = estimate_greedy_cost(nodes-1, request["k"], request["S_opt"])
    limits = request["full_greedy_limits"]
    result = {method: {"optimization_evaluator_calls_upper": 0, "optimization_CIC_upper": 0, "method_eligible": True, "method_skip_reason": None} for method in METHODS}
    ga = ga_evaluation_upper_bound(request["GA"])
    result["genetic_algorithm"].update(optimization_evaluator_calls_upper=ga, optimization_CIC_upper=ga*request["S_opt"])
    result["candidate_restricted_greedy"].update(optimization_evaluator_calls_upper=restricted.evaluation_count, optimization_CIC_upper=restricted.cic_simulation_count)
    reasons = []
    if full.evaluation_count > limits["max_evaluator_calls"]:
        reasons.append(f"Full_Greedy_calls_{full.evaluation_count}_exceed_{limits['max_evaluator_calls']}")
    if full.cic_simulation_count > limits["max_cic_simulations"]:
        reasons.append(f"Full_Greedy_CIC_{full.cic_simulation_count}_exceed_{limits['max_cic_simulations']}")
    result["full_greedy"] = {"optimization_evaluator_calls_upper": full.evaluation_count, "optimization_CIC_upper": full.cic_simulation_count,
                             "method_eligible": not reasons, "method_skip_reason": "; ".join(reasons) or None}
    if not reasons:
        raise ValueError("Full Greedy eligible: revise the declared method/CI matrix before adding it, never silently omit it")
    return result


def cost_preflight(request: dict, scenarios: list[dict], records: list[dict], descriptors: dict, repeats: int) -> dict:
    """Count all six methods/final batches, with one physical control per block."""
    rows = []
    for scenario in scenarios:
        d, node = scenario["dataset"], scenario["rumor_seeds"][0]
        costs = method_costs(request, scenario["node_count"])
        for method in METHODS:
            opt = costs[method]["optimization_CIC_upper"]*repeats
            final = request["S_eval_per_batch"][d]*request["final_batches"]*repeats
            phases = {"final": rate_proxy(d, node, method, "final", records, descriptors),
                      "selection_non_MC": rate_proxy(d, node, method, "selection_non_MC", records, descriptors)}
            if opt:
                phases["optimization"] = rate_proxy(d, node, method, "optimization", records, descriptors)
            quantities = {"final": final, "selection_non_MC": repeats, "optimization": opt}
            forecasts = {key: sum(quantities[phase]*proxy[key] for phase, proxy in phases.items())
                         for key in ("min_observed_rate", "max_observed_rate", "nearest_topology_proxy_rate")}
            rows.append({"dataset": d, "scenario_id": scenario["scenario_id"], "rumor_seeds": [node], "algorithm": method,
                         "repeats": repeats, "optimization_evaluator_calls_upper": costs[method]["optimization_evaluator_calls_upper"]*repeats,
                         "optimization_CIC_upper": opt, "final_evaluator_calls": request["final_batches"]*repeats, "final_CIC": final,
                         "observed_main_R_runtime_seconds": None, "main_R_point_estimate_seconds": None,
                         "proxy_min_seconds_before_safety": forecasts["min_observed_rate"],
                         "proxy_max_seconds_before_safety": forecasts["max_observed_rate"],
                         "nearest_topology_nominal_proxy_seconds": forecasts["nearest_topology_proxy_rate"],
                         "rate_evidence": phases, "scenario_runtime_identity_assumed": False})
    opt_calls = sum(r["optimization_evaluator_calls_upper"] for r in rows)
    final_calls = sum(r["final_evaluator_calls"] for r in rows)
    opt_cic = sum(r["optimization_CIC_upper"] for r in rows)
    final_cic = sum(r["final_CIC"] for r in rows)
    budget = request["admission_budget"]
    seconds = sum(r["proxy_max_seconds_before_safety"] for r in rows)
    projected = seconds*budget["runtime_safety_factor"]+budget["overhead_allowance_seconds"]
    reasons = []
    ga_runs = len(scenarios)*repeats
    if ga_runs > budget["max_ga_runs"]:
        reasons.append("GA_run_count_exceeds_budget")
    if opt_cic+final_cic > budget["max_cic_simulations"]:
        reasons.append("CIC_upper_bound_exceeds_budget")
    if projected > budget["max_projected_seconds"]:
        reasons.append("runtime_proxy_envelope_with_safety_and_overhead_exceeds_budget")
    return {"proposed_repeats": repeats, "scenarios": len(scenarios), "primary_methods": 6,
            "planned_primary_method_runs": len(rows)*repeats, "conditional_Full_Greedy_rows_skipped": len(scenarios)*repeats,
            "GA_runs": ga_runs, "optimization_evaluator_calls_upper": opt_calls, "final_evaluator_calls": final_calls,
            "total_evaluator_calls_upper": opt_calls+final_calls, "optimization_CIC_upper": opt_cic,
            "final_CIC": final_cic, "total_CIC_upper": opt_cic+final_cic,
            "runtime_proxy_min_seconds_before_safety": sum(r["proxy_min_seconds_before_safety"] for r in rows),
            "runtime_proxy_max_seconds_before_safety": seconds,
            "nearest_topology_nominal_proxy_seconds": sum(r["nearest_topology_nominal_proxy_seconds"] for r in rows),
            "projected_seconds_including_safety_and_overhead": projected,
            "runtime_headroom_seconds": budget["max_projected_seconds"]-projected,
            "within_declared_budget": not reasons, "admission_reasons": reasons, "rows": rows,
            "runtime_is_measured_on_main_R": False, "runtime_projection_is_hard_bound": False,
            "scope": "all six method selections and two final batches per P including shared NI; no duplicated control per comparator; no official CIC executed"}


def build_plan(request: dict) -> dict:
    """Pure planning/read-only topology; never change repeats based on admission."""
    base = validate_request(request)
    records, hashes = historical_rates()
    scenarios, descriptors, graphs = topology_audit(request, records)
    repeats = request["proposed_independent_runs"]
    preflight = cost_preflight(request, scenarios, records, descriptors, repeats)
    reservations = read_json(request["seed_reservation"])
    by_slot = {(r["scenario_id"], r["repetition_index"]): r for r in reservations}
    matrix = []
    for scenario in scenarios:
        costs = method_costs(request, scenario["node_count"])
        for repeat in range(repeats):
            slot = by_slot[(scenario["scenario_id"], repeat)]
            seed = make_experiment_seed_plan(request["master_seed"], scenario["scenario_index"]*100+repeat, request["seed_block_width"])
            s_eval = request["S_eval_per_batch"][scenario["dataset"]]
            bases = [seed.final_base_random_seed+b*s_eval for b in range(request["final_batches"])]
            if (slot["GA_random_seed"], slot["optimization_base_random_seed"], slot["final_batch_seeds"]) != (seed.ga_random_seed, seed.optimization_base_random_seed, bases):
                raise ValueError("Reserved main seed schedule changed")
            for method in (*METHODS, "full_greedy"):
                cost = costs[method]
                eligible = cost["method_eligible"]
                reason = cost["method_skip_reason"] if not eligible else "; ".join(preflight["admission_reasons"]) if not preflight["within_declared_budget"] else "awaiting_design_confirmation_and_validated_main_adapter"
                matrix.append({"unit_id": f"{scenario['scenario_id']}_r{repeat}_{method}", "dataset": scenario["dataset"],
                               "scenario_id": scenario["scenario_id"], "scenario_index": scenario["scenario_index"], "rumor_seeds": scenario["rumor_seeds"],
                               "algorithm": method, "repetition_index": repeat, "k": request["k"], "actual_P_size": 0 if method == "no_intervention" else request["k"],
                               "p": request["p"], "tie_breaking": request["tie_breaking"], "S_opt": request["S_opt"],
                               "S_eval_per_batch": s_eval, "final_batches": request["final_batches"], **request["GA"],
                               "master_seed": request["master_seed"], "seed_run_index": seed.independent_run_index,
                               "GA_random_seed": seed.ga_random_seed, "GA_operators_seed": make_seed_plan(seed.ga_random_seed, request["S_opt"], seed.optimization_base_random_seed).operators_seed,
                               "random_selection_seed": seed.random_selection_seed,
                               "optimization_base_random_seed": seed.optimization_base_random_seed,
                               "optimization_seed_stop_exclusive": seed.optimization_base_random_seed+request["S_opt"],
                               "final_batch_seeds": bases, "final_seed_stop_exclusive": bases[0]+request["final_batches"]*s_eval,
                               "candidate_pool_size": request["candidate_restricted_greedy"]["pool_size"] if method == "candidate_restricted_greedy" else None,
                               **cost, "budgeted_optimization_evaluator_calls_upper": cost["optimization_evaluator_calls_upper"] if eligible else 0,
                               "budgeted_optimization_CIC_upper": cost["optimization_CIC_upper"] if eligible else 0,
                               "budgeted_final_evaluator_calls": request["final_batches"] if eligible else 0,
                               "budgeted_final_CIC": request["final_batches"]*s_eval if eligible else 0,
                               "admission_status": "skipped_method_cost_limits" if not eligible else "blocked_global_preflight" if not preflight["within_declared_budget"] else "budget_eligible_pending_confirmation",
                               "execution_status": "not_executed_design_only", "reason": reason,
                               "protector_seeds": None, "measured_rumor_mean": None, "measured_runtime_seconds": None,
                               "actual_evaluator_calls": 0, "actual_CIC_simulations": 0})
    memory_probes = read_json("docs/cross_scenario_ga_confirmation/memory_probes.json")
    memory_forecast = 2*max(p["graph_and_copy_peak_RSS_bytes"] for p in memory_probes)+256*1024**2
    if memory_forecast > request["resource_limits"]["worker_RSS_bytes"]:
        preflight["admission_reasons"].append("worker_RSS_proxy_exceeds_cap")
        preflight["within_declared_budget"] = False
    if not preflight["within_declared_budget"]:
        for row in matrix:
            if row["method_eligible"]:
                row.update(admission_status="blocked_global_preflight", reason="; ".join(preflight["admission_reasons"]))
    # These arithmetic alternatives are not selected and never change the matrix.
    alternatives = [{"selected": False, "requires_user_confirmation": True,
                     **{k: v for k, v in cost_preflight(request, scenarios, records, descriptors, n).items() if k != "rows"}}
                    for n in (3, 4, 5, 10)]
    conditions = [
        {"id": "main_design_confirmation", "status": "pending", "requirement": "user confirms this concrete design before any execution"},
        {"id": "admission", "status": "passed" if preflight["within_declared_budget"] else "blocked", "requirement": preflight["admission_reasons"]},
        {"id": "repeats", "status": "proposed_not_confirmed", "requirement": "five independent runs proposed; do not auto-reduce on budget failure"},
        {"id": "main_budget", "status": "conservative_proposal", "requirement": "v1 budget was sensitivity-specific; confirm dedicated main allocation rather than assume its availability"},
        {"id": "new_R_timing", "status": "unmeasured", "requirement": "proxy envelopes and nearest-topology heuristic are not a calibrated new-R runtime model; no official observations generated"},
        {"id": "coverage", "status": "limited", "requirement": "two fixed high/constant R per graph, no medium/low holdout; keep existing low/legacy appendix and all low-spread main outcomes"},
        {"id": "main_adapter", "status": "not_implemented_not_authorized_here", "requirement": "validate all-method selection barrier, two batches per locked P, paired raw export and checkpoint ledger; old one-batch runner cannot be invoked twice and called one run"},
        {"id": "equivalence_margin", "status": "unconfirmed", "requirement": "no equivalence/practical-effect claims without a prespecified margin"},
        {"id": "power", "status": "not_established", "requirement": "five proposed runs do not guarantee power; no adaptive stopping based on significance"},
        {"id": "new_R_spread", "status": "unobserved_by_design", "requirement": "do not reroll R, retune GA or filter official low/no-spread outcomes"},
    ]
    for path in (request["source_protocol"], request["scenario_reservation"], request["seed_reservation"], "experiments/configs/pilot_2_calibration.json", "experiments/configs/cross_scenario_ga_confirmation.json"):
        hashes[path] = sha256_file(PROJECT_ROOT/path)
    hardware_path = "docs/cross_scenario_ga_confirmation/metadata.json"
    hardware = read_json(hardware_path)
    hashes[hardware_path] = sha256_file(PROJECT_ROOT/hardware_path)
    return {"request": request, "base_protocol": base, "scenarios": scenarios, "graphs": graphs, "runtime_records": records,
            "source_hashes": hashes, "matrix": matrix, "preflight": preflight, "alternatives": alternatives,
            "runtime_hardware_reference": {k: hardware.get(k) for k in ("python", "platform", "machine", "processor", "logical_cpu_count", "physical_memory_bytes", "libraries")},
            "memory": {"historical_graph_load_probes": memory_probes, "projected_worker_RSS_bytes": memory_forecast,
                       **request["resource_limits"], "memory_is_proxy_not_main_measurement": True},
            "unconfirmed_conditions": conditions, "supplementary_scenarios_retained": [r for r in read_json(base["scenario_manifest"]) if r["role"].startswith("supplementary")],
            "official_main_evaluator_calls": 0, "official_main_CIC_simulations": 0,
            "execution_gate": "blocked_until_both_valid_preflight_and_user_design_confirmation_and_validated_adapter",
            "automatic_repeat_change": False}


def grouped_preflight(plan: dict, group_key: str) -> list[dict]:
    """Roll up planning costs, never quality outcomes, by scenario or dataset."""
    result = []
    for key in sorted({r[group_key] for r in plan["preflight"]["rows"]}):
        rows = [r for r in plan["preflight"]["rows"] if r[group_key] == key]
        result.append({group_key: key, "dataset": rows[0]["dataset"],
                       "rumor_seeds": rows[0]["rumor_seeds"] if group_key == "scenario_id" else None,
                       **{field: sum(r[field] for r in rows) for field in ("optimization_evaluator_calls_upper", "optimization_CIC_upper", "final_evaluator_calls", "final_CIC", "proxy_min_seconds_before_safety", "proxy_max_seconds_before_safety", "nearest_topology_nominal_proxy_seconds")},
                       "planning_ceiling_seconds_with_safety_excluding_shared_overhead": sum(r["proxy_max_seconds_before_safety"] for r in rows)*plan["request"]["admission_budget"]["runtime_safety_factor"],
                       "actual_main_runtime_seconds": None, "runtime_identity_between_R_assumed": False})
    return result


def export_plan(plan: dict, destination: Path) -> dict:
    """Write a design-only package. No executor/--run mode is provided."""
    if destination.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Do not write into data")
    if destination.exists():
        raise FileExistsError("Do not overwrite a design freeze; use a new output directory/version")
    destination.mkdir(parents=True)
    summary = {"status": "stopped_at_preflight" if not plan["preflight"]["within_declared_budget"] else "budget_eligible_design_confirmation_pending",
               "GA_locked_by_user": True, "design_confirmed": False, "execution_authorized": False,
               "proposed_repeats": plan["request"]["proposed_independent_runs"],
               "matrix_rows": len(plan["matrix"]), "primary_method_rows": sum(r["method_eligible"] for r in plan["matrix"]),
               "full_greedy_rows_skipped": sum(not r["method_eligible"] for r in plan["matrix"]),
               "official_main_evaluator_calls": 0, "official_main_CIC_simulations": 0,
               "automatic_repeat_change": False, "preflight": {k: v for k, v in plan["preflight"].items() if k != "rows"}}
    for name, obj in (("config", plan["request"]), ("scenarios", plan["scenarios"]), ("graph_topology", plan["graphs"]),
                      ("matrix", plan["matrix"]), ("preflight", plan["preflight"]), ("preflight_by_method_scenario", plan["preflight"]["rows"]),
                      ("preflight_by_scenario", grouped_preflight(plan, "scenario_id")), ("preflight_by_dataset", grouped_preflight(plan, "dataset")),
                      ("repeat_alternatives_not_selected", plan["alternatives"]), ("runtime_rate_provenance", plan["runtime_records"]),
                      ("runtime_source_hashes", plan["source_hashes"]), ("memory_plan", plan["memory"]),
                      ("runtime_hardware_reference", plan["runtime_hardware_reference"]),
                      ("unconfirmed_conditions", plan["unconfirmed_conditions"]), ("supplementary_scenarios_retained", plan["supplementary_scenarios_retained"]),
                      ("analysis_policy", plan["request"]["analysis_policy"]), ("summary", summary)):
        atomic_json(destination/f"{name}.json", obj)
        if isinstance(obj, list):
            write_csv(destination/f"{name}.csv", obj)
    atomic_json(destination/"design_fingerprint.json", {"version": plan["request"]["protocol_version"], "sha256": fingerprint(plan),
                "source_hashes": plan["source_hashes"], "GA_change_after_main_observations_allowed": False,
                "code_change_to_semantics_allowed": False})
    return summary


def write_report(plan: dict, target: Path, destination: Path) -> None:
    """Describe fixed choices, proposed choices, blocked admission and statistics."""
    q, pre = plan["request"], plan["preflight"]
    repeats = q["proposed_independent_runs"]
    blocks = len(plan["scenarios"])*repeats
    scenarios = plan["scenarios"]
    topology = "\n".join(f"| {s['dataset']} | {s['rumor_seeds']} | {s['stratum']} | {s['reachable_count']} | {s['propagation_degree']} | {s['in_degree'] if s['directed'] else '—'} | {s['SCC_or_component_size']} | {s['WCC_or_component_size']} | {100*s['no_intervention_no_growth_probability_analytic']:.2f}% |" for s in scenarios)
    costs = "\n".join(f"| {r['dataset']} | {r['rumor_seeds']} | {r['optimization_evaluator_calls_upper']+r['final_evaluator_calls']} | {r['optimization_CIC_upper']+r['final_CIC']} | {r['nearest_topology_nominal_proxy_seconds']:.2f} | [{r['proxy_min_seconds_before_safety']:.2f}, {r['proxy_max_seconds_before_safety']:.2f}] | {r['planning_ceiling_seconds_with_safety_excluding_shared_overhead']:.2f} |" for r in grouped_preflight(plan, "scenario_id"))
    dcosts = "\n".join(f"| {r['dataset']} | {r['optimization_evaluator_calls_upper']+r['final_evaluator_calls']} | {r['optimization_CIC_upper']+r['final_CIC']} | {r['planning_ceiling_seconds_with_safety_excluding_shared_overhead']:.2f} |" for r in grouped_preflight(plan, "dataset"))
    full = "\n".join(f"| {g['dataset']} | {method_costs(q,g['nodes'])['full_greedy']['optimization_evaluator_calls_upper']} | {method_costs(q,g['nodes'])['full_greedy']['optimization_CIC_upper']} | skipped: vượt calls100 và CIC2000 |" for g in plan["graphs"])
    alternatives = "\n".join(f"| {a['proposed_repeats']} | {a['planned_primary_method_runs']} | {a['total_evaluator_calls_upper']} | {a['total_CIC_upper']} | {a['projected_seconds_including_safety_and_overhead']:.2f} | {'fit proxy budget' if a['within_declared_budget'] else 'vượt budget'} | chưa chọn/cần xác nhận |" for a in plan["alternatives"])
    conditions = "\n".join(f"| {r['id']} | {r['status']} | {r['requirement']} |" for r in plan["unconfirmed_conditions"])
    verification_path = destination/"verification.json"
    verification = json.loads(verification_path.read_text()) if verification_path.exists() else None
    check = f"**{verification['tests_passed']}/{verification['tests_run']} tests pass**; {verification['protected_files_checked']} existing files giữ checksum, gồm {verification['data_files_checked']} data files. Không thêm/xóa file dữ liệu." if verification else "Full tests/checksums sẽ được điền sau verification cuối."
    status = "BLOCKED AT PREFLIGHT" if not pre["within_declared_budget"] else "BUDGET ELIGIBLE; DESIGN CONFIRMATION STILL REQUIRED"
    target.write_text(f"""# Main Experiments Protocol — Design Freeze & Computational Preflight

**Trạng thái: {status}.** Đã khóa GA theo yêu cầu người dùng; ma trận và phân
tích main là thiết kế reviewable, chưa được xác nhận để thực thi. Đã chạy
**0 main evaluator calls, 0 main CIC simulations**. Không có số đo chất lượng
main, không gọi GA/baseline/evaluator trên sáu R main. Projection không được
trình bày như runtime thực đo hoặc hard upper bound.

## 1. Các thông số khóa và lựa chọn còn cần xác nhận

GA **N10/G10, crossover0.8, mutation0.1, tournament3, elitism1, cache=True**;
S_opt100, p=.03, k5, protector-priority. Không tiếp tục điều chỉnh GA sau khi
thấy main outcomes. Khóa theo yêu cầu hiện tại, không tuyên bố đây là cấu hình
tối ưu/tương đương từ các CI chứa0 của confirmation. Frozen Protocol-v1 JSON
và các báo cáo trước giữ nguyên; file main specification là phiên bản riêng.

S_eval email6.000/batch; Facebook/Wiki2.500/batch, B=2; pooled final S12.000/
5.000 mỗi P. Candidate-Restricted Greedy top10 out-degree với directed graph,
degree với undirected, ngoài R; score ties ascending actual integer ID.
Degree ranking cũng theo out-degree/degree. PageRank alpha=.85,tol=1e-12,
max_iter1000, weight=None như Pilot2. Random chọn đúng5 distinct nodes ngoàiR
bằng seed đã reserve, không giả định ID liên tục. Mọi method giữ semantics cũ.

**Đề xuất {repeats} independent runs/scenario/method**, chưa xác nhận. Request
nêu rationale cho lựa chọn này; không tuyên bố đã có power analysis. 10 slots
reserve trước đây chưa phải main repeat count đã duyệt. Ma trận đề xuất bị chặn nếu admission fail;
không tự đổi thành4/3 rồi gọi đó là thiết kế đã chốt.

## 2. Kiểm tra sáu rumor scenarios bảo lưu

Đã tái tạo đúng sampling SHA256/Random master2026111112 của confirmation:
uniform actual IDs trong high stratum (>2/3 reachable maximum), hoặc constant
cho Facebook, loại mọi R trong Pilot2 manifest. Đối chiếu thêm R tuning/
confirmation, Protocol Validation R577/2162/4341 và email smoke R0: không trùng.
Không dùng GA/baseline quality để chọn lại, không đổi R hoặc sinh lại sample.
Source JSON/CSV và sampling seed/hash được lưu nguyên ở scenarios.json.

| Dataset | R | Stratum | Reachable (gồm R) | Out-degree/degree | In-degree | SCC/component | WCC/component | Analytic NI no-growth |
|---|---|---|---:|---:|---:|---:|---:|---:|
{topology}

Reachability tính chính xác theo hướng cạnh, giữ node/edge gốc. CSV còn có
degree rank/ties, local clustering và expected first-layer size=p*d.
**P(No Intervention không lan khỏi seed)=(1−p)^d** vì processed graph đơn,
không self-loop, một source và các attempts tới distinct neighbors độc lập.
Đây là phân tích toán học, **không phải MC observation**, cũng không là công
thức no-growth của CIC khi có protector seeds.

Sáu scenarios bao phủ degree/first-step risk khác nhau trong high/constant
strata: đặc biệt Wiki1961 d5/no-growth85.87% so với Wiki1795 d44/26.18%.
Reachable cao không bảo đảm mean spread lớn. Hai email cùng reachable965
nhưng degree khác; Facebook cùng connected graph vẫn có source degree14/24.
Không phân loại main rumor mean/saturation khi chưa có outcomes. Giữ nguyên
Wiki1961 và mọi main outcome ít/không spread; không áp gate dựa trên GA score.

Coverage chỉ có hai fixed R/graph, p=.03/k5, không đại diện uniform toàn V,
không đo p/k sensitivity hoặc interactions. Medium strata của email/Wiki rỗng;
main holdouts chưa có low-reach sources. Giữ low/legacy R761/767,5288/6009/4341
trong supplementary manifest. Chúng đã dùng calibration, nên appendix phải
ghi exploratory/prior-data, không gán lại thành official main holdouts. Thêm
low-reach main scenarios mới cần revision/sampling/preflight riêng, không âm
thầm bổ sung hoặc loại R hiện có theo kết quả.

## 3. Ma trận phương pháp và chính sách seed

6 methods: No Intervention, Random, Degree, PageRank, Candidate-Restricted
Greedy, GA. **6R×{repeats}runs×6methods={blocks*6} primary rows**, thêm{blocks} Full-Greedy rows
với status/reason riêng; matrix.csv tổng{len(plan['matrix'])}rows. {blocks} scenario/repeat blocks,
mỗi block có **12 final calls** (6methods×2batches), trong đó control chỉ2
calls, không nhân control thêm một lần cho từng comparator.

Mọi method cùng R, budget k5 (NI có P rỗng là mốc), p, tie và final schedule
trong block. Degree/PageRank được chọn lại theo cùng deterministic rule ở mỗi
repeat để runtime selection nhất quán; P giống nhau không là nhiều independent
algorithm draws. Không cache fitness qua phương pháp hoặc runs. Restricted
Greedy là biến thể riêng, không đổi tên thành Full Greedy.

| Dataset | Full Greedy calls mỗi selection | CIC ở S_opt100 | Trạng thái |
|---|---:|---:|---|
{full}

Những bound Full vẫn được ghi dù bị skipped; budgeted work của skipped method
=0, không giả rumor mean=0. Eligibility 6methods không đồng nghĩa đã qua global
admission. Primary rows có status blocked_global_preflight khi vượt tổng
budget; tất cả execution_status=not_executed_design_only, P/quality/runtime=null.

Main master2026111109; giữ đúng60 seed slots đã reserve, dùng{repeats}slots đầu mỗiR,
{10-repeats}slots còn lại không tự kích hoạt. Index=scenario_index*100+repeat, ordinal
11..16; block width1.000.000 theo Cantor-pair helper cũ. GA input/operator và
Random Selection seeds có domain separation. GA và Greedy cùng fixed100 opt
seed labels trong block để so sánh công bằng; cache cục bộ. Final dùng nửa sau
block, batch b=final_base+b*S_eval; cùng lịch giữa tất cả methods, độc lập opt,
khác repeats/R và các namespace pilot/confirmation. Cùng seed không bảo đảm
common random edge outcomes khi valid attempts phụ thuộc P. Không đổi master,
R, N/G/rates hoặc S sau khi xem main outcomes.

## 4. Computational preflight — counts và runtime proxies

GA U=N+G(N−E)=100 evaluator calls/run trước cache. Restricted pool10,k5 cần
10+9+8+7+6=40calls/run. {blocks}GA +{blocks}restricted selections; deterministic baselines
không gọi fitness MC. Final2batches được tính đủ cho mọi P.

| Phase | Calls upper | CIC upper |
|---|---:|---:|
| Optimization | {pre['optimization_evaluator_calls_upper']} | {pre['optimization_CIC_upper']} |
| Final của cả6methods, gồm control | {pre['final_evaluator_calls']} | {pre['final_CIC']} |
| Tổng | {pre['total_evaluator_calls_upper']} | {pre['total_CIC_upper']} |

Giới hạn đề xuất giữ bảo thủ capGA120/CIC3.000.000/time10.800s/safety1.5 của
v1. **V1 ghi rõ cap đó cho sensitivity, chưa tự cấp ngân sách main**: main
allocation vẫn cần xác nhận; không tự nâng cap để admission pass.

Rates đo tại p=.03/k5 từ Pilot2, pilot-v1, Reduced V2 và Cross-Scenario,
tách method/optimization/final/non-MC. Lấy accuracy prefix2500, không coi các
nested prefixes nhỏ hơn là independent records. Có nhiều R/P/timings, nhưng
chưa có rate đo trên sáu mainR. Nearest topology proxy dùng khoảng cách
|log(1+d_main)−log(1+d_old)|+|reachable_fraction difference| để chọn reference
R cho **nominal heuristic**, chưa được chứng minh là mô hình runtime nhân quả.

Admission dùng **max observed rate trong toàn cohort cùng dataset/method/phase**,
không dùng best timing hoặc giả final rate của GA là rate của mọi baseline.
Proxy min/max và nearest reference R từng phase được lưu. Actual runtime/main-R
point estimate=null. Hai scenarios có thể chung conservative planning ceiling;
đó không phải khẳng định chúng tốn thời gian bằng nhau. Unknown variation trên
R/P/hardware mới được ghi rõ, factor1.5 không là bảo đảm hard bound.

| Dataset | R | Calls upper | CIC upper | Nearest proxy raw s | Observed-rate envelope raw s | Planning ceiling×1.5 s |
|---|---|---:|---:|---:|---|---:|
{costs}

| Dataset,2R×{repeats}runs | Calls upper | CIC upper | Planning ceiling s trước shared overhead |
|---|---:|---:|---:|
{dcosts}

Sum max-rate proxy trước safety={pre['runtime_proxy_max_seconds_before_safety']:.3f}s;
×1.5 +overhead300s = **{pre['projected_seconds_including_safety_and_overhead']:.3f}s**.
Runtime headroom={pre['runtime_headroom_seconds']:.3f}s. Admission reasons:
**{'; '.join(pre['admission_reasons']) or 'none'}**. Đây là budget rejection
trước execution, không phải đã dùng hết3h hoặc algorithms bị lỗi.

Không thay repeats để vượt gate. Các phương án dưới là tính toán, **chưa chọn**:

| Repeats | Primary rows | Calls upper | CIC upper | Projected safety+overhead s | Admission | Quyền chạy |
|---|---:|---:|---:|---:|---|---|
{alternatives}

Nếu giữ{repeats}repeats, cần xác nhận main time allocation ít nhất
{pre['projected_seconds_including_safety_and_overhead']:.3f}s theo proxy này,
cộng thêm headroom phù hợp; con số đó không bảo đảm actual fit. Nếu không
tăng budget, chọn repeat count khác phải là quyết định revision được xác nhận,
giữ mọi R/method/S và đánh giá ảnh hưởng đến độ chính xác. Không tự dùng cache
hits dự kiến để biến counts upper thành actual thấp hơn nhằm qua admission.

## 5. RAM, timeout và checkpoint/resume dự kiến

Concurrency1; worker RSS cap2GiB, parent allowance512MiB. Historical graph+
deepcopy peak probes (không diffusion) cho memory proxy
2×max probe+256MiB={plan['memory']['projected_worker_RSS_bytes']/1024**2:.1f}MiB;
đây chưa là RAM main đo thực, PageRank/Greedy/P khác cần guard. Selection
timeout900s/method; final timeout120s/batch, luôn giới hạn theo remaining
active global budget. RSS watchdog ru_maxrss/heartbeat0.5s như confirmation;
không là instantaneous memory ceiling hoặc virtual-address-space limit.

Kế hoạch state machine: pending→selected→selection barrier→final_batch0/1→
complete→analyzed. Khóa toàn bộ P trong matrix trước any final outcomes.
Mỗi selection/batch publish JSON atomic+SHA256; GA lưu full parameters/seeds,
fitness/cache/calls/CIC/generation history. Lưu raw final counts/seed indices
cho paired covariance. Controls perblock/batch được gọi một lần, downstream
metrics reference control IDs thay vì rerun. Selection timing tách fitnessMC,
final timing tách control, loading/import/guard/export và total active ledger.

Resume phải match config/scenario/graph/core/P/seed fingerprints, không chạy
lại completed units, không reset active time/CIC budget. Unknown interrupted
work charge CIC upper +timeout, giữ failed attempt logs, không ghi unknown=0.
Không reselect P sau final outcome; retry cùng seed/params nếu được resource
gate cho phép. Không thay input để "cứu" phương pháp kém.

**Stage này chỉ xuất design, chưa triển khai execution adapter**. Existing
Milestone6 runner là one-batch; gọi hai lần để tạo B2 sẽ re-optimize hoặc đổi
context, không được xem là một run/P. Bounded V2 bridge chỉ hỗ trợ GA. Cần
adapter all-methods two-batch được kiểm thử lại trước main, dùng nguyên API
selection/evaluate_cic, không đổi semantics. CLI thiết kế không có --run.

## 6. Statistical analysis plan cố định trước kết quả

Primary per-scenario metric: pooled mean rumor count từ B2 batches **cho P
cố định của từng independent algorithm run**. Estimate μ_s,a=mean_r(μhat_s,a,r).
Report sampleSD giữa run means, conditional MC SD/SE/CI từngP/batch/pooled,
min/max/no-growth fraction và training−final gap riêng cho optimizer.
Training fitness không làm final quality; thế hệ và MC observations không
được đếm thành thêm independent GA runs.

Primary comparisons: GA−NI/Random/Degree/PageRank/Restricted trong mỗi6R,
30contrasts. Pair bằng cùngR/repeat/final seed schedule; δ_r=μhat_GA−μhat_cmp.
Pointwise descriptive CI95=t_(n−1,.975)*SD(δ_r)/sqrt(n) quanh meanδ. Dùng
**one predeclared family45 effects**:30scenario +15within-dataset contrasts
(3datasets×5comparators), Bonferroni approximate simultaneous95% t intervals
với quantile1−.05/(2×45), df=n−1. Multiplicity không tạo pooled global rank.
Không thêm baseline-vs-baseline hypothesis sau khi xem plots. Confidence
coverage xấp xỉ với n={repeats}/rare cascades, không tuyên bố power đã đủ.

Trong mỗi dataset, hai fixed R có weight1/2. Với repeat r, bundle contrast=
(δ_s0,r+δ_s1,r)/2; CI qua{repeats} independent bundles, conditional trên hai R đã
chọn, **không gọi đó là10 independent scenario draws**. Vẫn báo từng scenario,
range/direction consistency; không suy rộng CI thành population of all rumor
sources. Không gộp node counts/weighted winner giữa ba datasets; chỉ bảng
riêng, cùng cách phân tích. Như vậy heterogeneity không bị giấu bởi average.

Spread reduction s,a =1−μ_s,a/μ_s,NI (**ratio of across-run means**, không tự
đổi sang mean of ratios). Dataset summary là equal mean của hai scenario
reductions, tránh ngầm weight theo control spread. Report absolute reduction
và percent points. Paired **Fieller ratio CI mô tả** sử dụng covariance giữa
paired run means; nếu interval unbounded/disjoint/denominator uncertainty lớn,
báo nguyên dạng, không clip hoặc ép finite. Spread-ratio CIs không là extra
primary significance tests trong family45; winner statements chỉ dựa trên
primary rumor contrasts. Nếu cần inference riêng về ratio, xác nhận family
mở rộng trước main. NI≥1 vì |R|1, nhưng approximate denominator CI vẫn có thể
chạm0 trong low-spread/noisy cases; không thay R để né vấn đề đó.

Conditional MC SE của paired difference tính trên aligned individual CIC
counts (shared seed labels không đảm bảo edge coupling). Between-run variance
chứa selection randomness +MC noise. Giữ raw Var(run means)−mean(MC SE²), kể
cả âm, display nonnegative riêng; không suy "GA hoàn toàn ổn định" từ giá trị
âm. Deterministic NI/Degree/PageRank có cùngP, nên selection variability bằng0
theo cấu trúc; những final repeats chủ yếu đoMC, không phải stochastic algorithm
draws. Random/Greedy-MC/GA có selection variability. Bundle MC variance với
independent scenario seed blocks là sum(w_s²×conditional variance_s).

CI family chứa0: **chưa đủ bằng chứng khác biệt**, không equivalence. Mean
gần nhau hoặc rounding ties ghi unresolved/descriptive tie, không ép strict
ranking. Practical-equivalence margin hiện null, chưa có meaningful-effect
threshold; không tự đặt ngưỡng thuận lợi cho GA. Mean ordering/pointwise plots
chỉ mô tả, không là primary winner selection khi family CI chưa phân biệt.
Không optional stopping/repeats tăng giảm sau significance, không bỏ low/no-
spread scenarios, không retune GA theo bất kỳ main data nào.

## 7. Điều kiện chưa xác nhận, tests và provenance

| Điều kiện | Trạng thái | Yêu cầu |
|---|---|---|
{conditions}

{check}
Semantics IC/CIC/MC/GA/Greedy/baseline, raw/processed và các experiments cũ
giữ nguyên. Root .DS_Store/zip và các thay đổi đã có trong workspace được giữ.
Mọi cost là upper counts hoặc proxy có provenance, không có fake main results.

Artifacts ở [docs/main_experiments_protocol](docs/main_experiments_protocol):
matrix.csv/json, scenarios.csv/json, preflight.json, preflight_by_scenario/
dataset/method_scenario, runtime_rate_provenance.csv/json, source hashes,
repeat_alternatives_not_selected, memory_plan, analysis_policy và
unconfirmed_conditions.csv/json. Request:
[main_experiments_protocol.json](experiments/configs/main_experiments_protocol.json).

```sh
.venv/bin/python -B -m experiments.design_main_experiments --output-dir docs/main_design_repeat
.venv/bin/python -B -m unittest discover -s tests -q
```
Lệnh trên chỉ xuất planning artifacts vào folder mới. Exit0 chỉ có nghĩa
export thành công; summary.status/admission quyết định preflight, không phải
đã cấp quyền chạy. Main execution tiếp tục bị chặn tới khi cả budget/design/
adapter đều hợp lệ và được xác nhận.
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=PROJECT_ROOT/"experiments/configs/main_experiments_protocol.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    plan = build_plan(request)
    destination = args.output_dir.resolve() if args.output_dir else PROJECT_ROOT/request["output_directory"]
    summary = export_plan(plan, destination)
    report_target = destination/"MAIN_EXPERIMENTS_PROTOCOL.md" if args.output_dir else PROJECT_ROOT/"MAIN_EXPERIMENTS_PROTOCOL.md"
    write_report(plan, report_target, destination)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
