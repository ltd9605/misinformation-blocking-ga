"""Materialize the requested reduced screen; no GA/CIC execution in this CLI."""

import argparse
from collections import Counter
from copy import deepcopy
import json
from math import ceil
from pathlib import Path

from experiments.design_protocol_v1 import load_exported_design, load_protocol
from experiments.pilot_protocol_validation import write_csv, write_json
from src.algorithms import make_seed_plan
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.sensitivity import FACTORS, computational_preflight, sensitivity_seed_plan


GA_KEYS = ("population_size", "max_generations", "crossover_rate", "mutation_rate", "tournament_size", "elitism_count", "cache_fitness")
CONSTANT_FIELDS = ("scenario_id", "dataset", "rumor_seeds", "k", "p", "tie_breaking", "S_opt", "S_eval",
                   "final_batches", "repetition_index", "master_seed", "GA_random_seed", "GA_operators_seed",
                   "optimization_base_random_seed", "final_batch_0_base_random_seed", "final_batch_1_base_random_seed")


def validate_ofat_pair(reference: dict, alternative: dict, factor: str) -> None:
    """Reject cross-scenario, mismatched-seed or multi-factor comparisons."""
    if factor not in FACTORS or any(reference[k] != alternative[k] for k in CONSTANT_FIELDS):
        raise ValueError("OFAT comparison changes non-factor conditions")
    changed = [key for key in GA_KEYS if reference[key] != alternative[key]]
    if changed != [factor]:
        raise ValueError("OFAT comparison must change exactly its declared factor")


def plan_reduced_screen(request: dict) -> dict:
    """Read Protocol-v1 profiles directly, apply the explicit five-run request.

    The old stored authorization flag does not cancel the new user request.
    The independent computational-budget gate still takes precedence.
    """
    repetitions = request["requested_independent_runs"]
    if type(repetitions) is not int or repetitions < 2:
        raise ValueError("Use at least two independent GA runs")
    if request["screen_master_seed"] == request["reserved_main_master_seed"]:
        raise ValueError("Screen and reserved main seed namespaces must differ")
    if request["full_design_authorized"] or request["main_experiments_authorized"]:
        raise ValueError("This request must not authorize full/main experiments")
    base_path = PROJECT_ROOT/request["protocol_path"]
    protocol = load_protocol(base_path)
    if request["screen_master_seed"] == protocol["random_seed_policy"]["master_seed"]:
        raise ValueError("Do not reuse the Protocol-v1 pilot seed namespace")
    design = load_exported_design(protocol, PROJECT_ROOT/request["exported_protocol_design"])
    by_id = {p["profile_id"]: p for p in design["profiles"]}
    profiles = [by_id[name] for name in protocol["reduced_profiles"]]
    if (len(profiles) != 5 or profiles[0]["profile_id"] != "reference"
            or Counter(p["changed_factor"] for p in profiles[1:]) != Counter(FACTORS)):
        raise ValueError("Reduced matrix must be reference plus one alternative for each of four factors")
    reference_panels = {r["factor"] for r in design["panel_rows"] if r["profile_id"] == "reference"}
    if reference_panels != set(FACTORS) or len(design["profiles"]) != 9:
        raise ValueError("Expected nine unique profiles and reference in all four OFAT panels")
    effective = deepcopy(protocol)
    effective["independent_runs"]["reduced_screen"] = repetitions
    effective["random_seed_policy"]["master_seed"] = request["screen_master_seed"]
    effective["execution_authorization"]["reduced_screen"] = True  # Current user authorization; budget remains unchanged.
    preflight = computational_preflight(effective, profiles, design["development"], repetitions, design["rates"], protocol["design_budget"])
    original = computational_preflight(protocol, profiles, design["development"], protocol["independent_runs"]["reduced_screen"], design["rates"], protocol["design_budget"])
    matrix = []
    for scenario in design["development"]:
        for repeat in range(repetitions):
            seed = sensitivity_seed_plan(effective, scenario["scenario_index"], repeat)
            s_eval = protocol["S_eval_per_batch"][scenario["dataset"]]
            for profile in profiles:
                core_seeds = make_seed_plan(seed["operators_input_seed"], protocol["S_opt"], seed["optimization_base_seed"])
                matrix.append({"run_id": f"{scenario['scenario_id']}_r{repeat}_{profile['profile_id']}",
                               "profile_id": profile["profile_id"], "scenario_id": scenario["scenario_id"],
                               "dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                               "k": protocol["k"], "p": protocol["p"], "tie_breaking": protocol["tie_breaking"],
                               "S_opt": protocol["S_opt"], "S_eval": s_eval, "final_batches": protocol["final_batches"],
                               "total_final_simulations_per_P": s_eval*protocol["final_batches"], **profile["parameters"],
                               "repetition_index": repeat, "scenario_index": scenario["scenario_index"],
                               "master_seed": request["screen_master_seed"], "GA_random_seed": seed["operators_input_seed"],
                               "GA_operators_seed": core_seeds.operators_seed,
                               "optimization_base_random_seed": seed["optimization_base_seed"],
                               "optimization_seed_stop_exclusive": seed["optimization_base_seed"]+protocol["S_opt"],
                               "final_batch_0_base_random_seed": seed["final_base_seed"],
                               "final_batch_1_base_random_seed": seed["final_base_seed"]+s_eval,
                               "final_seed_stop_exclusive": seed["final_base_seed"]+2*s_eval,
                               "block_start": seed["block_start"], "block_stop_exclusive": seed["block_stop_exclusive"],
                               "OFAT_panels": list(FACTORS) if profile["profile_id"] == "reference" else [profile["changed_factor"]]})
    pairs = []
    for scenario in design["development"]:
        for repeat in range(repetitions):
            rows = [r for r in matrix if r["scenario_id"] == scenario["scenario_id"] and r["repetition_index"] == repeat]
            reference = next(r for r in rows if r["profile_id"] == "reference")
            for profile in profiles[1:]:
                alternative = next(r for r in rows if r["profile_id"] == profile["profile_id"])
                validate_ofat_pair(reference, alternative, profile["changed_factor"])
                pairs.append({"factor": profile["changed_factor"], "dataset": scenario["dataset"],
                              "rumor_seeds": scenario["rumor_seeds"], "repetition_index": repeat,
                              "reference_run_id": reference["run_id"], "alternative_run_id": alternative["run_id"],
                              "validated_one_factor_only": True})
    # Optional future alternatives are arithmetic proposals only, never selected.
    smaller = deepcopy(profiles)
    for p in smaller:
        if p["changed_factor"] == "population_size":
            p["profile_id"], p["parameters"]["population_size"] = "population_size_15", 15
        elif p["changed_factor"] == "max_generations":
            p["profile_id"], p["parameters"]["max_generations"] = "max_generations_15", 15
    alternative_cost = computational_preflight(effective, smaller, design["development"], repetitions, design["rates"], protocol["design_budget"])
    by_dataset = [{"dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                   **{k: v for k, v in computational_preflight(effective, profiles, [scenario], repetitions,
                       design["rates"], protocol["design_budget"]).items() if k != "rows"}} for scenario in design["development"]]
    return {"request": request, "base_protocol": protocol, "effective_protocol": effective,
            "base_protocol_sha256": sha256_file(base_path), "source_manifest_sha256": design["manifest_sha256"],
            "all_nine_profiles": design["profiles"], "all_OFAT_panels": design["panel_rows"], "selected_profiles": profiles,
            "development_scenarios": design["development"], "rates": design["rates"],
            "reserved_validation_scenarios": [s for s in design["scenarios"] if s["scenario_id"] in protocol["validation_scenario_ids"]],
            "requested_preflight": preflight, "original_three_repeat_preflight": original,
            "preflight_by_dataset": by_dataset,
            "matrix": matrix, "pairs": pairs,
            "future_alternative_smaller_levels": {"status": "unselected_requires_protocol_revision", "profiles": smaller, "preflight": alternative_cost},
            "budget_minimum_seconds_if_only_time_cap_changes": ceil(preflight["rate_projection_seconds_with_safety"])}


def export_plan(plan: dict, destination: Path) -> dict:
    """Export reviewable planned/skipped rows with null quality metrics; no simulation calls."""
    if destination.exists():
        raise FileExistsError(f"Do not overwrite screen artifacts: {destination}")
    if destination.resolve().is_relative_to((PROJECT_ROOT/"data").resolve()):
        raise ValueError("Do not write into data")
    destination.mkdir(parents=True)
    (destination/"runs").mkdir()
    preflight = plan["requested_preflight"]
    blocked = not preflight["within_declared_budget"]
    status = "skipped_global_preflight" if blocked else "not_executed_preflight_only"
    reason = "; ".join(preflight["budget_reasons"]) if blocked else "this_command_exports_preflight_only"
    results = []
    for row in plan["matrix"]:
        result = {**row, "status": status, "reason": reason, "protector_seeds": None,
                  "training_fitness": None, "independent_evaluation_mean": None, "independent_evaluation_std": None,
                  "independent_evaluation_CI_low": None, "independent_evaluation_CI_high": None,
                  "optimization_runtime_seconds": None, "evaluation_runtime_seconds": None,
                  "cache_hits": None, "actual_evaluator_calls": 0, "actual_CIC_simulations": 0}
        results.append(result)
        write_json(destination/"runs"/f"{row['run_id']}.json", result)
    write_json(destination/"request.json", plan["request"])
    write_json(destination/"effective_protocol.json", plan["effective_protocol"])
    write_json(destination/"all_nine_configurations.json", plan["all_nine_profiles"])
    selected = {p["profile_id"] for p in plan["selected_profiles"]}
    write_csv(destination/"all_nine_configurations.csv", [{"profile_id": p["profile_id"], "selected_for_reduced": p["profile_id"] in selected,
              "omission_reason": None if p["profile_id"] in selected else "not_in_Protocol_v1_reduced_profiles", **p["parameters"]} for p in plan["all_nine_profiles"]])
    write_csv(destination/"OFAT_panel_membership.csv", plan["all_OFAT_panels"])
    write_csv(destination/"run_matrix.csv", plan["matrix"])
    write_json(destination/"run_matrix.json", plan["matrix"])
    write_csv(destination/"OFAT_comparisons.csv", plan["pairs"])
    write_json(destination/"OFAT_comparisons.json", plan["pairs"])
    write_csv(destination/"run_results.csv", results)
    write_json(destination/"run_results.json", results)
    write_json(destination/"preflight_requested_5_repeats.json", preflight)
    write_csv(destination/"preflight_requested_5_repeats.csv", preflight["rows"])
    write_json(destination/"preflight_original_3_repeats.json", plan["original_three_repeat_preflight"])
    write_csv(destination/"preflight_by_dataset.csv", plan["preflight_by_dataset"])
    write_json(destination/"preflight_by_dataset.json", plan["preflight_by_dataset"])
    write_json(destination/"future_alternative_smaller_levels.json", plan["future_alternative_smaller_levels"])
    write_json(destination/"pilot2_rate_evidence.json", plan["rates"])
    write_json(destination/"main_evaluation_reservation.json", {
        "screen_master_seed": plan["request"]["screen_master_seed"], "reserved_main_master_seed": plan["request"]["reserved_main_master_seed"],
        "validation_scenario_ids": plan["base_protocol"]["validation_scenario_ids"],
        "reserved_validation_scenarios": plan["reserved_validation_scenarios"],
        "main_authorized": False, "screen_results_are_official_main_evidence": False,
        "prior_pilot_results_reused_as_screen_runs": False, "main_observations_generated": 0})
    figures = [{"figure_group": name, "status": "not_generated_no_completed_screen_runs", "reason": reason}
               for name in (*FACTORS, "reference_convergence", "quality_vs_cost")]
    write_csv(destination/"figure_status.csv", figures)
    write_json(destination/"figure_status.json", figures)
    group_summary = [{"dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                      "profile_id": profile["profile_id"], "planned_independent_GA_runs": plan["request"]["requested_independent_runs"],
                      "completed_independent_GA_runs": 0, "status": status, "reason": reason,
                      "mean_independent_final_result": None, "between_GA_run_std": None,
                      "conditional_MC_SE": None, "GA_run_CI_low": None, "GA_run_CI_high": None}
                     for scenario in plan["development_scenarios"] for profile in plan["selected_profiles"]]
    write_csv(destination/"summary_by_configuration.csv", group_summary)
    write_json(destination/"summary_by_configuration.json", group_summary)
    summary = {"status": "stopped_at_preflight" if blocked else "preflight_only_no_executor_invoked",
               "unique_Protocol_v1_profiles": len(plan["all_nine_profiles"]), "selected_reduced_profiles": len(selected),
               "reference_in_all_four_panels": True, "original_45_runs_meaning": "5 profiles * 3 scenarios * 3 repetitions TOTAL; 15 per dataset/scenario",
               "requested_GA_runs": len(results), "requested_GA_runs_per_scenario": len(selected)*plan["request"]["requested_independent_runs"],
               "independent_runs_per_profile_per_scenario": plan["request"]["requested_independent_runs"],
               "completed_GA_runs": 0, "skipped_GA_runs": len(results) if blocked else 0,
               "actual_screen_evaluator_calls": 0, "actual_screen_CIC_simulations": 0,
               "preflight": {k: v for k, v in preflight.items() if k != "rows"},
               "minimum_projected_time_budget_to_fit_seconds": plan["budget_minimum_seconds_if_only_time_cap_changes"],
               "GA_recommendation": "retain_reference_for_reproducibility_only_no_new_screen_evidence_not_optimality",
               "reference_GA_parameters_retained": plan["base_protocol"]["reference_ga"],
               "full_design_executed": False, "main_experiments_executed": False, "test_simulations_excluded_from_screen_counters": True}
    write_json(destination/"summary.json", summary)
    write_json(destination/"provenance.json", {"Protocol_v1_sha256": plan["base_protocol_sha256"],
               "scenario_manifest_sha256": plan["source_manifest_sha256"],
               "new_user_request_authorizes_conditional_screen": True, "stop_reason_is_budget_not_old_authorization_flag": blocked})
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=PROJECT_ROOT/"experiments/configs/milestone_7_reduced_screen.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    request = json.loads(args.request.read_text())
    plan = plan_reduced_screen(request)
    destination = args.output_dir.resolve() if args.output_dir else (PROJECT_ROOT/request["output_directory"]).resolve()
    summary = export_plan(plan, destination)
    p = plan["requested_preflight"]
    print(f"{summary['status']}: {p['GA_runs']} planned GA runs, <= {p['total_evaluator_calls_upper']} evaluator calls, <= {p['total_CIC_upper']} CIC")
    print(f"Runtime projection {p['rate_projection_seconds_with_safety']:.3f}s vs cap {plan['base_protocol']['design_budget']['max_projected_seconds']}s; no GA/CIC executor invoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
