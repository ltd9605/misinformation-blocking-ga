"""Export Protocol v1 design and preflight only; never starts GA or CIC."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from experiments.pilot_protocol_validation import write_csv, write_json
from src.algorithms import select_degree
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.experiments.sensitivity import build_ofat_matrix, computational_preflight, full_greedy_cost_record, sensitivity_seed_plan


def load_protocol(path: Path) -> dict:
    """Load a reference specification, deliberately distinct from runner JSON."""
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol["execution_authorization"]["main_experiments"] or protocol["execution_authorization"]["full_parameter_sweep"]:
        raise ValueError("This stage must not authorize main/full sweep")
    if protocol["analysis_policy"]["select_using_training_fitness"]:
        raise ValueError("Training fitness cannot select the final experimental winner")
    if type(protocol["final_batches"]) is not int or protocol["final_batches"] < 2:
        raise ValueError("Use at least two independent final MC batches")
    if type(protocol["S_opt"]) is not int or protocol["S_opt"] < 1:
        raise ValueError("Invalid S_opt")
    if any(type(v) is not int or v < 1 for v in protocol["S_eval_per_batch"].values()):
        raise ValueError("Invalid S_eval")
    if set(protocol["development_scenario_ids"]) & set(protocol["validation_scenario_ids"]):
        raise ValueError("Development and validation scenarios overlap")
    sensitivity_seed_plan(protocol, 0, 0)
    return protocol


def measured_pilot2_rates() -> dict:
    """Worst observed N10/G10/S100 rates; do not use best GA quality to filter."""
    source = PROJECT_ROOT / "docs/pilot_2_calibration"
    optimization = json.loads((source / "optimization_results.json").read_text())
    accuracy = json.loads((source / "accuracy_statistics.json").read_text())
    representatives = json.loads((source / "representatives.json").read_text())
    rates = {}
    for dataset, scenario in representatives.items():
        rows = [r for r in optimization if r["dataset"] == dataset and r["phase"] == "optimization"
                and r["S_opt"] == 100 and r["algorithm"] == "genetic_algorithm"]
        final = [r for r in accuracy if r["dataset"] == dataset and r["S_eval"] == 2500 and r["algorithm"] == "genetic_algorithm"]
        control = [r for r in accuracy if r["dataset"] == dataset and r["S_eval"] == 2500 and r["algorithm"] == "no_intervention"]
        rates[dataset] = {"scenario_id": scenario["scenario_id"], "rumor_seeds": scenario["rumor_seeds"], "p": scenario["p"],
                          "fitness_seconds_per_cic": max(r["optimization_evaluator_seconds"]/r["optimization_cic_simulations"] for r in rows),
                          "GA_non_MC_seconds": max(r["selection_runtime_seconds"]-r["optimization_evaluator_seconds"] for r in rows),
                          "GA_final_seconds_per_cic": max(r["runtime_prefix_MC_seconds"]/r["S_eval"] for r in final),
                          "control_seconds_per_cic": max(r["runtime_prefix_MC_seconds"]/r["S_eval"] for r in control),
                          "evidence": "Pilot2 p=.03, two GA runs and two independent fixed-P accuracy batches; new profiles not measured"}
    return rates


def build_design(protocol: dict) -> dict:
    """Materialize scenarios, OFAT profiles and three explicitly separate scopes."""
    manifest = PROJECT_ROOT / protocol["scenario_manifest"]
    scenarios = json.loads(manifest.read_text())
    by_id = {s["scenario_id"]: {**s, "scenario_index": i} for i, s in enumerate(scenarios)}
    selected_ids = protocol["development_scenario_ids"] + protocol["validation_scenario_ids"]
    if any(s not in by_id for s in selected_ids):
        raise ValueError("Unknown frozen scenario ID")
    development = [by_id[s] for s in protocol["development_scenario_ids"]]
    panel_rows, profiles = build_ofat_matrix(protocol["reference_ga"], protocol["factor_levels"])
    profile_lookup = {p["profile_id"]: p for p in profiles}
    rates = measured_pilot2_rates()
    full = computational_preflight(protocol, profiles, development, protocol["independent_runs"]["full_design"], rates, protocol["design_budget"])
    reduced_profiles = [profile_lookup[p] for p in protocol["reduced_profiles"]]
    reduced = computational_preflight(protocol, reduced_profiles, development, protocol["independent_runs"]["reduced_screen"], rates, protocol["design_budget"])
    pilot_spec = protocol["pilot"]
    pilot_profiles = [profile_lookup[p] for p in pilot_spec["profile_ids"]]
    pilot_scenarios = [by_id[s] for s in pilot_spec["scenario_ids"]]
    if any(s["scenario_id"] not in protocol["development_scenario_ids"] for s in pilot_scenarios):
        raise ValueError("Pilot must preserve algorithm-outcome validation scenarios")
    pilot_budget = {"max_ga_runs": pilot_spec["max_ga_runs"], "max_cic_simulations": pilot_spec["max_cic_simulations"],
                    "max_projected_seconds": pilot_spec["max_wall_seconds"]}
    pilot = computational_preflight(protocol, pilot_profiles, pilot_scenarios, protocol["independent_runs"]["pilot"], rates, pilot_budget)
    pilot_schedule = []
    for scenario in pilot_scenarios:
        for run in range(protocol["independent_runs"]["pilot"]):
            # Counterbalance profile order; seeds never depend on this order.
            order = pilot_profiles if run % 2 == 0 else list(reversed(pilot_profiles))
            for profile in order:
                pilot_schedule.append({"run_id": f"{scenario['scenario_id']}_r{run}_{profile['profile_id']}",
                                       "scenario": scenario, "independent_run_index": run, "profile": profile,
                                       "seeds": sensitivity_seed_plan(protocol, scenario["scenario_index"], run)})
    return {"protocol": deepcopy(protocol), "scenarios": list(by_id.values()), "development": development,
            "panel_rows": panel_rows, "profiles": profiles, "rates": rates,
            "preflights": {"full_design": full, "reduced_screen": reduced, "pilot": pilot},
            "pilot_schedule": pilot_schedule, "manifest_sha256": sha256_file(manifest)}


def load_exported_design(protocol: dict, directory: Path) -> dict:
    """Reject drift in frozen scenarios, schedule or evidence before execution."""
    frozen = json.loads((directory/"design.json").read_text())
    if json.loads((directory/"protocol.json").read_text()) != protocol or frozen["protocol"] != protocol:
        raise ValueError("Exported design and requested protocol differ")
    if sha256_file(PROJECT_ROOT/protocol["scenario_manifest"]) != frozen["manifest_sha256"]:
        raise ValueError("Frozen scenario manifest changed")
    current = build_design(protocol)
    if current["pilot_schedule"] != frozen["pilot_schedule"] or current["rates"] != frozen["rates"]:
        raise ValueError("Frozen schedule or Pilot2 rate evidence changed")
    return frozen


def export_design(design: dict, destination: Path) -> None:
    """Write reviewable artifacts before the bounded pilot is allowed to run."""
    if destination.exists():
        raise FileExistsError(f"Design already exists: {destination}")
    if destination.resolve().is_relative_to((PROJECT_ROOT / "data").resolve()):
        raise ValueError("Do not export into data")
    destination.mkdir(parents=True)
    protocol = design["protocol"]
    write_json(destination / "protocol.json", protocol)
    write_csv(destination / "parameter_matrix.csv", design["panel_rows"])
    write_json(destination / "unique_configurations.json", design["profiles"])
    write_csv(destination / "unique_configurations.csv", [{"profile_id": p["profile_id"], "changed_factor": p["changed_factor"], **p["parameters"]} for p in design["profiles"]])
    write_json(destination / "pilot_schedule.json", design["pilot_schedule"])
    write_json(destination / "pilot2_runtime_evidence.json", design["rates"])
    for name, preflight in design["preflights"].items():
        write_json(destination / f"preflight_{name}.json", preflight)
        write_csv(destination / f"preflight_{name}.csv", preflight["rows"])
    scenarios, pools, full_costs, reference = [], [], [], []
    graphs = {name: load_processed_graph(PROJECT_ROOT / "data/processed" / name) for name in protocol["datasets"]}
    for scenario in design["scenarios"]:
        role = ("development" if scenario["scenario_id"] in protocol["development_scenario_ids"] else
                "algorithm_outcome_validation" if scenario["scenario_id"] in protocol["validation_scenario_ids"] else "supplementary")
        scenarios.append({**scenario, "protocol_role": role})
        graph = graphs[scenario["dataset"]]
        if set(scenario["rumor_seeds"]).difference(graph):
            raise ValueError("Frozen rumor ID missing from processed graph")
        pools.append({"scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"],
                      "candidate_nodes": sorted(select_degree(graph, scenario["rumor_seeds"], protocol["restricted_greedy"]["pool_size"])),
                      "pool_rule": protocol["restricted_greedy"]["ranking"]})
        full_costs.append({"scenario_id": scenario["scenario_id"], "dataset": scenario["dataset"],
                           **full_greedy_cost_record(len(graph), len(scenario["rumor_seeds"]), protocol)})
    for scenario in design["development"]:
        name = scenario["dataset"]
        reference.append({"dataset": name, "reference_R": scenario["rumor_seeds"], "reachability": scenario["reachable_count"],
                          "reachability_group": scenario["stratum"], "k": protocol["k"], "p": protocol["p"],
                          "tie_breaking": protocol["tie_breaking"], "S_opt": protocol["S_opt"],
                          "S_eval_per_batch": protocol["S_eval_per_batch"][name], "independent_final_batches": protocol["final_batches"],
                          "total_final_simulations_per_P": protocol["S_eval_per_batch"][name]*protocol["final_batches"],
                          "reference_evidence": "S_opt100 measured but not proven stable; email S_eval6000 extrapolated before this pilot" if name == "email-Eu-core" else "Pilot2 S_opt100/S_eval2500 measured on reference R only",
                          **protocol["reference_ga"]})
    write_csv(destination / "reference_configuration.csv", reference)
    write_json(destination / "reference_configuration.json", reference)
    write_csv(destination / "scenario_manifest.csv", scenarios)
    write_json(destination / "scenario_manifest.json", scenarios)
    write_csv(destination / "restricted_candidate_pools.csv", pools)
    write_csv(destination / "full_greedy_status.csv", full_costs)
    unresolved = [
        ("MC_fitness_accuracy", "S_opt100 has residual selection/validation gaps, particularly Wiki; no optimum claim"),
        ("email_final_accuracy", "S_eval6000 was a Pilot2 extrapolation; bounded pilot only validates limited P/R contexts"),
        ("rumor_scenario_coverage", "Validation R858/1555/2110 have control scans but no GA quality tuning; supplementary low cases retained"),
        ("replication_power", "10 full/3 reduced runs are design choices, not a completed statistical-power analysis; pilot has 2"),
        ("parameter_levels", "Proposed levels support OFAT screening; no global optimum or interactions established"),
        ("practical_effect", "Equivalence margin is unset; uncertain pairs cannot be called equal or strictly ranked"),
        ("multiplicity", "Confirm comparison family/multiplicity policy before inferential full study"),
        ("runtime_transfer", "Rates measured on one R per dataset; new P/N/G/R can change work; forecasts are not measured upper bounds"),
        ("secondary_probability", "p=.05/.10 not authorized in this sensitivity plan; require separate protocol/calibration"),
        ("main_authorization", "Full sweep, reduced screen and main experiments remain disabled until explicitly authorized")]
    write_csv(destination / "unconfirmed_conditions.csv", [{"condition": a, "detail": b} for a, b in unresolved])
    write_json(destination / "unconfirmed_conditions.json", [{"condition": a, "detail": b} for a, b in unresolved])
    write_json(destination / "design.json", design)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT / "experiments/configs/experiment_protocol_v1.json")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "docs/experiment_protocol_v1")
    args = parser.parse_args(argv)
    design = build_design(load_protocol(args.protocol.resolve()))
    export_design(design, args.output_dir.resolve())
    for name, p in design["preflights"].items():
        print(f"{name}: {p['GA_runs']} GA runs; <= {p['total_evaluator_calls_upper']} evaluator calls; <= {p['total_CIC_upper']} CIC; projected {p['rate_projection_seconds_with_safety']:.1f}s; within_budget={p['within_declared_budget']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
