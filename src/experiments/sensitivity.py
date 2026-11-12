"""OFAT protocol design and cost projections; no optimizer/model implementations."""

from copy import deepcopy
from math import isfinite, sqrt
from statistics import mean, variance
from typing import Any

from src.algorithms import estimate_greedy_cost
from .seeds import make_experiment_seed_plan


FACTORS = ("population_size", "max_generations", "crossover_rate", "mutation_rate")


def validate_ga_parameters(parameters: dict[str, Any]) -> None:
    """Validate a planned parameter set without running fitness evaluation."""
    for key, minimum in (("population_size", 1), ("max_generations", 0), ("tournament_size", 1), ("elitism_count", 0)):
        if type(parameters[key]) is not int or parameters[key] < minimum:
            raise ValueError(f"Invalid {key}")
    if max(parameters["tournament_size"], parameters["elitism_count"]) > parameters["population_size"]:
        raise ValueError("Tournament/elite count exceeds population")
    for key in ("crossover_rate", "mutation_rate"):
        value = parameters[key]
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Invalid {key}")
    if type(parameters["cache_fitness"]) is not bool:
        raise ValueError("cache_fitness must be boolean")


def build_ofat_matrix(reference: dict[str, Any], levels: dict[str, list]) -> tuple[list[dict], list[dict]]:
    """Return panel rows and deduplicated profiles, sharing one baseline run."""
    validate_ga_parameters(reference)
    if set(levels) != set(FACTORS):
        raise ValueError("Exactly four sensitivity factors are required")
    profiles = [{"profile_id": "reference", "changed_factor": None, "parameters": deepcopy(reference)}]
    rows = []
    for stage, factor in enumerate(FACTORS, start=1):
        values = levels[factor]
        if not values or len(set(values)) != len(values) or reference[factor] not in values:
            raise ValueError("Unique factor levels must contain the reference")
        for value in values:
            parameters = {**reference, factor: value}
            validate_ga_parameters(parameters)
            is_reference = parameters == reference
            profile_id = "reference" if is_reference else f"{factor}_{format(value, 'g').replace('.', 'p')}"
            if not is_reference:
                profiles.append({"profile_id": profile_id, "changed_factor": factor, "parameters": parameters})
            rows.append({"stage": stage, "factor": factor, "value": value, "profile_id": profile_id,
                         "is_reference": is_reference, "baseline_reuse": "same physical baseline run per scenario/run",
                         **parameters})
    return rows, profiles


def ga_evaluation_upper_bound(parameters: dict[str, Any]) -> int:
    """Uncached upper bound; fixed-sample cache can only reduce actual calls."""
    validate_ga_parameters(parameters)
    return parameters["population_size"] + parameters["max_generations"] * (parameters["population_size"]-parameters["elitism_count"])


def sensitivity_seed_plan(protocol: dict, scenario_index: int, run_index: int) -> dict:
    """Profile-independent paired seed labels; independent scenario/run blocks."""
    policy = protocol["random_seed_policy"]
    if type(run_index) is not int or not 0 <= run_index < policy["scenario_run_stride"]:
        raise ValueError("Run index exceeds scenario stride")
    if type(scenario_index) is not int or scenario_index < 0:
        raise ValueError("Invalid scenario index")
    plan = make_experiment_seed_plan(policy["master_seed"], scenario_index*policy["scenario_run_stride"]+run_index, policy["block_width"])
    if max(protocol["S_eval_per_batch"].values())*protocol["final_batches"] > policy["block_width"]//2:
        raise ValueError("Final batches exceed reserved half block")
    if protocol["S_opt"] > policy["block_width"]//2:
        raise ValueError("Fitness samples exceed reserved half block")
    return {"operators_input_seed": plan.ga_random_seed, "optimization_base_seed": plan.optimization_base_random_seed,
            "final_base_seed": plan.final_base_random_seed, "block_start": plan.block_start,
            "block_stop_exclusive": plan.block_start+policy["block_width"], "scenario_run_index": scenario_index*policy["scenario_run_stride"]+run_index}


def computational_preflight(protocol: dict, profiles: list[dict], scenarios: list[dict], independent_runs: int,
                             rates: dict[str, dict], budget: dict) -> dict:
    """Separate arithmetic upper counts from non-guaranteed Pilot-2 rate forecasts.

    Controls are shared once per scenario/run/batch, not once per GA profile.
    Baseline profiles must be deduplicated before this function is called.
    """
    if type(independent_runs) is not int or independent_runs < 1:
        raise ValueError("Independent runs must be positive")
    if len({p["profile_id"] for p in profiles}) != len(profiles):
        raise ValueError("Deduplicate physical baseline profiles")
    ga_runs = len(profiles)*len(scenarios)*independent_runs
    training_calls = sum(ga_evaluation_upper_bound(p["parameters"]) for p in profiles)*len(scenarios)*independent_runs
    final_calls = ga_runs*protocol["final_batches"]
    controls = len(scenarios)*independent_runs*protocol["final_batches"]
    rows = []
    seconds = 0.0
    for scenario in scenarios:
        dataset = scenario["dataset"]
        rate = rates[dataset]
        s_eval = protocol["S_eval_per_batch"][dataset]
        control_cic = independent_runs*protocol["final_batches"]*s_eval
        seconds += control_cic*rate["control_seconds_per_cic"]
        for profile in profiles:
            calls = ga_evaluation_upper_bound(profile["parameters"])*independent_runs
            training_cic = calls*protocol["S_opt"]
            final_cic = independent_runs*protocol["final_batches"]*s_eval
            reference = protocol["reference_ga"]
            parameters = profile["parameters"]
            history_scale = max(1.0, parameters["population_size"]*(parameters["max_generations"]+1)/(reference["population_size"]*(reference["max_generations"]+1)))
            forecast = (training_cic*rate["fitness_seconds_per_cic"]+final_cic*rate["GA_final_seconds_per_cic"]
                        +independent_runs*rate["GA_non_MC_seconds"]*history_scale)
            seconds += forecast
            rows.append({"scenario_id": scenario["scenario_id"], "dataset": dataset, "rumor_seeds": scenario["rumor_seeds"],
                         "profile_id": profile["profile_id"], "independent_runs": independent_runs,
                         "optimization_evaluator_calls_upper": calls, "optimization_cic_upper": training_cic,
                         "final_evaluator_calls": independent_runs*protocol["final_batches"], "final_cic": final_cic,
                         "control_cic_shared_per_scenario": control_cic,
                         "projected_seconds_excluding_shared_control": forecast,
                         "rate_evidence_scope": rate["scenario_id"], "projection_is_measurement": False})
    training_cic = training_calls*protocol["S_opt"]
    final_cic = sum(row["final_cic"] for row in rows)
    control_cic = sum(independent_runs*protocol["final_batches"]*protocol["S_eval_per_batch"][s["dataset"]] for s in scenarios)
    total_cic = training_cic+final_cic+control_cic
    projected = seconds*protocol["design_budget"]["runtime_safety_factor"]
    reasons = []
    if ga_runs > budget["max_ga_runs"]:
        reasons.append("GA_run_count_exceeds_budget")
    if total_cic > budget["max_cic_simulations"]:
        reasons.append("CIC_upper_bound_exceeds_budget")
    if projected > budget["max_projected_seconds"]:
        reasons.append("Pilot2_rate_projection_exceeds_budget")
    return {"unique_parameter_configurations": len(profiles), "scenario_configurations": len(profiles)*len(scenarios),
            "independent_runs": independent_runs, "GA_runs": ga_runs, "fitness_evaluator_calls_upper": training_calls,
            "GA_final_evaluator_calls": final_calls, "control_evaluator_calls": controls,
            "total_evaluator_calls_upper": training_calls+final_calls+controls,
            "fitness_CIC_upper": training_cic, "GA_final_CIC": final_cic, "control_CIC": control_cic,
            "total_CIC_upper": total_cic, "rate_projection_seconds_before_safety": seconds,
            "rate_projection_seconds_with_safety": projected, "runtime_is_measured": False,
            "runtime_is_hard_upper_bound": False, "within_declared_budget": not reasons, "budget_reasons": reasons,
            "rows": rows, "cost_scope": "GA optimization + two final batches + shared controls; excludes raw exports/loading/setup",
            "uncertainty": "Pilot2 rates from one R per dataset; different genotypes/N/G/hardware load can change speed; safety factor is not a guarantee"}


def full_greedy_cost_record(node_count: int, rumor_count: int, protocol: dict) -> dict:
    """Record why Full Greedy cannot be silently substituted or executed."""
    cost = estimate_greedy_cost(node_count-rumor_count, protocol["k"], protocol["S_opt"])
    limits = protocol["full_greedy_limits"]
    allowed = cost.evaluation_count <= limits["max_evaluator_calls"] and cost.cic_simulation_count <= limits["max_cic_simulations"]
    return {"evaluator_calls": cost.evaluation_count, "CIC_simulations": cost.cic_simulation_count,
            "status": "eligible_after_runtime_check" if allowed else "skipped", "reason": None if allowed else "explicit_Full_Greedy_calls_or_CIC_limit"}


def variance_components(final_means: list[float], conditional_MC_SEs: list[float]) -> dict:
    """Descriptive MC/GA variation decomposition, not a power/coverage guarantee.

    Independent GA runs are the units. Conditional MC observations are not
    additional GA repetitions. Keep the raw variance difference if it is
    negative; a nonnegative display estimate is separately named.
    """
    if len(final_means) != len(conditional_MC_SEs) or len(final_means) < 2:
        raise ValueError("Use at least two matching independent GA runs")
    from scipy.stats import t
    total = variance(final_means)
    mc = mean(s*s for s in conditional_MC_SEs)
    se = sqrt(total/len(final_means))
    half = float(t.ppf(.975, len(final_means)-1))*se
    return {"independent_GA_runs": len(final_means), "mean_over_GA_runs": mean(final_means),
            "between_GA_run_mean_variance_including_MC": total,
            "mean_conditional_MC_variance_of_final_mean": mc,
            "GA_variance_component_untruncated": total-mc,
            "GA_variance_component_nonnegative_display": max(0.0, total-mc),
            "CI95_over_GA_run_means_low": mean(final_means)-half,
            "CI95_over_GA_run_means_high": mean(final_means)+half,
            "small_run_count_warning": len(final_means) < 5}
