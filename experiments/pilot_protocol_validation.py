"""Bounded protocol validation on fixed scenarios, not thesis experiments."""

import argparse
import csv
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any

from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import DATASETS, PROJECT_ROOT
from src.experiments import ExperimentConfig
from src.experiments.config import ALGORITHMS
from src.experiments.metadata import environment_metadata
from src.experiments.protocol import (
    fixed_rumor_scenario, plan_methods, precision_diagnostics, projected_runtime, spread_diagnostics,
)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        if not rows:
            return
        keys = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def snapshot() -> dict[str, str]:
    paths = [p for folder in ("data", "src/data", "src/diffusion", "src/evaluation", "src/algorithms")
             for p in (PROJECT_ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths.append(PROJECT_ROOT / "requirements.txt")
    return {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p) for p in sorted(paths)}


def load_settings(path: Path, output_override: Path | None = None) -> dict[str, Any]:
    settings = json.loads(path.read_text(encoding="utf-8"))
    required = {"purpose", "datasets", "rumor_seed_count", "k", "propagation_probabilities", "tie_breaking",
                "S_opt", "S_eval", "independent_runs", "random_seed", "seed_block_size", "ga_parameters",
                "pagerank_parameters", "candidate_pool_size", "limits", "resources", "smoke", "diagnostics",
                "save_raw_observations", "output_directory"}
    if not isinstance(settings, dict) or set(settings) != required:
        raise ValueError("Protocol configuration has missing/unknown keys")
    names = settings["datasets"]
    if not isinstance(names, list) or not names or any(n not in DATASETS for n in names) or len(set(names)) != len(names):
        raise ValueError("Use unique registered datasets")
    probabilities = settings["propagation_probabilities"]
    if (not isinstance(probabilities, list) or not probabilities
            or any(type(p) not in (int, float) or not 0 <= p <= 1 for p in probabilities)
            or len(set(probabilities)) != len(probabilities)):
        raise ValueError("Use unique probabilities in [0,1]")
    for name in ("independent_runs", "rumor_seed_count", "candidate_pool_size"):
        if type(settings[name]) is not int or settings[name] < 1:
            raise ValueError(f"Invalid {name}")
    if settings["save_raw_observations"] is not True:
        raise ValueError("Protocol diagnostics require raw final observations")
    resources = settings["resources"]
    if set(resources) != {"max_total_wall_seconds", "max_comparison_wall_seconds", "runtime_safety_factor"}:
        raise ValueError("Invalid resource keys")
    if any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in resources.values()) or resources["runtime_safety_factor"] < 1:
        raise ValueError("Invalid resource limits")
    smoke = settings["smoke"]
    if set(smoke) != {"p", "S_opt", "S_eval", "ga_parameters"}:
        raise ValueError("Invalid smoke keys")
    diagnostics = settings["diagnostics"]
    if set(diagnostics) != {"low_spread_fraction", "saturation_fraction", "target_opt_se_fraction", "target_eval_se_fraction", "precision_prefixes"}:
        raise ValueError("Invalid diagnostic keys")
    for key in ("low_spread_fraction", "saturation_fraction", "target_opt_se_fraction", "target_eval_se_fraction"):
        if type(diagnostics[key]) not in (int, float) or not 0 < diagnostics[key] <= 1:
            raise ValueError(f"Invalid {key}")
    prefixes = diagnostics["precision_prefixes"]
    if not isinstance(prefixes, list) or not prefixes or any(type(s) is not int or s < 1 for s in prefixes) or len(set(prefixes)) != len(prefixes):
        raise ValueError("Invalid precision prefixes")
    output = output_override if output_override is not None else Path(settings["output_directory"])
    settings["output_directory"] = (output if output.is_absolute() else path.parent / output).resolve().as_posix()
    return settings


def comparison_values(settings: dict[str, Any], scenario: dict[str, Any], root: Path,
                       phase: str, p: float, index: int, case_id: str) -> dict[str, Any]:
    common = {key: settings[key] for key in ("k", "tie_breaking", "S_opt", "S_eval", "random_seed", "seed_block_size",
                                             "ga_parameters", "pagerank_parameters", "limits", "save_raw_observations")}
    if phase == "smoke":
        common.update({key: settings["smoke"][key] for key in ("S_opt", "S_eval", "ga_parameters")})
    return {**common, "dataset": scenario["dataset"], "rumor_seeds": scenario["rumor_seeds"], "p": p,
            "independent_run_index": index, "purpose": f"pilot_protocol_validation_{phase}_only",
            "candidate_restriction": {"method": "degree", "size": settings["candidate_pool_size"]},
            "output_directory": (root / "runs" / phase / case_id).as_posix()}


def execute_case(config: ExperimentConfig, config_path: Path, timeout: float, logs: Path) -> dict[str, Any]:
    """Use a child process for a hard resource cap; partial runs never count as zero work."""
    started = perf_counter()
    try:
        completed = subprocess.run([sys.executable, "-B", "-m", "experiments.run_experiment", "--config", str(config_path)],
                                   cwd=PROJECT_ROOT, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        (logs / f"{config_path.stem}.log").write_text(str(error), encoding="utf-8")
        return {"status": "timed_out", "reason": f"Hard wall cap {timeout:.3f}s exceeded; partial CIC work unknown",
                "subprocess_wall_seconds": perf_counter() - started, "run_directory": None}
    (logs / f"{config_path.stem}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    status = "completed" if completed.returncode == 0 else "failed"
    return {"status": status, "reason": None if status == "completed" else completed.stderr.strip(),
            "subprocess_wall_seconds": perf_counter() - started,
            "run_directory": config.run_directory.as_posix() if status == "completed" else None}


def collect_outputs(root: Path, cases: list[dict[str, Any]], scenarios: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Aggregate only measured results; retain skipped/failed rows separately."""
    results, statuses, convergence, gaps, precision = [], [], [], [], []
    controls: dict[tuple[str, float], list[int]] = {}
    for case in cases:
        context = {key: case[key] for key in ("case_id", "phase", "dataset", "p", "replicate_index", "independent_run_index")}
        if case["status"] != "completed":
            for planned in case["preflight"]:
                statuses.append({**context, "algorithm": planned["algorithm"], "status": planned["status"] if planned["status"] == "skipped" else case["status"],
                                 "reason": planned["reason"] if planned["status"] == "skipped" else case["reason"],
                                 "actual_cic_simulations": 0 if case["status"] == "skipped" or planned["status"] == "skipped" else None})
            continue
        directory = Path(case["run_directory"])
        summary = json.loads((directory / "summary.json").read_text())
        for status in summary["method_statuses"]:
            statuses.append({**context, **status, "actual_cic_simulations": status["cic_simulations"]})
        for row in summary["results"]:
            results.append({**context, **row, "comparison_runner_total_seconds": summary["timings"]["total_experiment_runtime_seconds"],
                            "comparison_subprocess_wall_seconds": case["subprocess_wall_seconds"], "run_directory": str(directory)})
            if row["optimization_best_estimated_fitness"] is not None:
                gap = row["rumor_mean"] - row["optimization_best_estimated_fitness"]
                n = scenarios[case["dataset"]]["node_count"]
                threshold = max(settings["diagnostics"]["target_opt_se_fraction"] * n, 2 * (row["rumor_standard_error"] or 0))
                gaps.append({**context, "algorithm": row["algorithm"], "optimization_fitness": row["optimization_best_estimated_fitness"],
                             "independent_rumor_mean": row["rumor_mean"], "final_SE": row["rumor_standard_error"],
                             "final_minus_optimization": gap, "gap_fraction_of_graph": gap / n,
                             "descriptive_gap_threshold": threshold, "large_descriptive_gap": abs(gap) > threshold})
        with (directory / "raw_observations.csv").open(newline="") as stream:
            observations = list(csv.DictReader(stream))
        by_method: dict[str, list[int]] = {}
        for observation in observations:
            by_method.setdefault(observation["algorithm"], []).append(int(observation["rumor_count"]))
        if case["phase"] == "pilot":
            controls.setdefault((case["dataset"], case["p"]), []).extend(by_method["no_intervention"])
            diagnostics = settings["diagnostics"]
            for method, counts in by_method.items():
                for row in precision_diagnostics(counts, scenarios[case["dataset"]]["node_count"], diagnostics["precision_prefixes"],
                                                 diagnostics["target_opt_se_fraction"], diagnostics["target_eval_se_fraction"]):
                    precision.append({**context, "algorithm": method, **row})
        if (directory / "convergence.csv").exists():
            with (directory / "convergence.csv").open(newline="") as stream:
                convergence.extend({**context, **row} for row in csv.DictReader(stream))
    spread = []
    for (dataset, p), counts in controls.items():
        scenario = scenarios[dataset]
        spread.append({"dataset": dataset, "p": p, "rumor_seeds": scenario["rumor_seeds"],
                       "node_count": scenario["node_count"], "reachable_node_count": scenario["reachable_node_count"],
                       **spread_diagnostics(counts, node_count=scenario["node_count"], rumor_count=len(scenario["rumor_seeds"]),
                                            reachable_count=scenario["reachable_node_count"], low_fraction=settings["diagnostics"]["low_spread_fraction"],
                                            saturation_fraction=settings["diagnostics"]["saturation_fraction"])})
    for name, rows in (("results", results), ("method_status", statuses), ("convergence", convergence),
                       ("fitness_gaps", gaps), ("mc_precision", precision), ("spread_diagnostics", spread)):
        write_csv(root / f"{name}.csv", rows)
    write_json(root / "method_status.json", statuses)
    summary = {"purpose": settings["purpose"], "official_experiment": False,
               "completed_smoke_comparisons": sum(c["status"] == "completed" and c["phase"] == "smoke" for c in cases),
               "completed_pilot_comparisons": sum(c["status"] == "completed" and c["phase"] == "pilot" for c in cases),
               "skipped_comparisons": sum(c["status"] == "skipped" for c in cases),
               "failed_or_timed_out_comparisons": sum(c["status"] in ("failed", "timed_out") for c in cases),
               "successful_method_rows": len(results), "skipped_method_rows": sum(s["status"] == "skipped" for s in statuses),
               "measured_completed_cic_simulations": sum(r["optimization_cic_simulations"] + r["final_cic_simulations"] for r in results),
               "partial_work_unknown": any(c["status"] in ("failed", "timed_out") for c in cases),
               "spread_diagnostics": spread, "fitness_gaps": gaps,
               "comparison_records": [{k: v for k, v in c.items() if k != "preflight"} for c in cases]}
    write_json(root / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "experiments/configs/pilot_protocol_validation.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    settings = load_settings(args.config.resolve(), args.output_dir.resolve() if args.output_dir else None)
    root = Path(settings["output_directory"])
    # Match the runner's data protections before creating any directory.
    if root.is_relative_to((PROJECT_ROOT / "data").resolve()):
        raise ValueError("Protocol output must not be inside data")
    root.mkdir(parents=True, exist_ok=False)
    for folder in ("configs", "logs"):
        (root / folder).mkdir()
    started = perf_counter()
    write_json(root / "protocol_config.json", settings)
    before = snapshot()
    write_json(root / "integrity_before.json", before)
    write_json(root / "environment.json", environment_metadata())
    graphs = {name: load_processed_graph(PROJECT_ROOT / "data/processed" / name) for name in settings["datasets"]}
    scenarios = {name: fixed_rumor_scenario(graph, name, settings["random_seed"], settings["rumor_seed_count"])
                 for name, graph in graphs.items()}
    write_json(root / "rumor_scenarios.json", scenarios)  # Persist before any simulation.
    cases = []
    for phase in ("smoke", "pilot"):
        for d, (name, graph) in enumerate(graphs.items()):
            for j, p in enumerate([settings["smoke"]["p"]] if phase == "smoke" else settings["propagation_probabilities"]):
                for replicate in range(1 if phase == "smoke" else settings["independent_runs"]):
                    index = (len(graphs) * len(settings["propagation_probabilities"]) * settings["independent_runs"] + d
                             if phase == "smoke" else (d * len(settings["propagation_probabilities"]) + j) * settings["independent_runs"] + replicate)
                    case_id = f"{phase}_{name}_p{p:g}_r{replicate}"
                    config, estimates = plan_methods(graph, comparison_values(settings, scenarios[name], root, phase, p, index, case_id))
                    path = root / "configs" / f"{case_id}.json"
                    write_json(path, config.to_dict())
                    cases.append({"case_id": case_id, "phase": phase, "dataset": name, "p": p,
                                  "replicate_index": replicate, "independent_run_index": index,
                                  "status": "pending", "reason": None, "config_path": path.as_posix(),
                                  "preflight": estimates, "projected_runtime_seconds": None})
    write_json(root / "preflight.json", cases)
    write_csv(root / "preflight.csv", [{k: v for k, v in c.items() if k != "preflight"} | cost for c in cases for cost in c["preflight"]])
    completed_cases, smoke_summaries = [], {}
    resources = settings["resources"]
    for case in cases:
        remaining = resources["max_total_wall_seconds"] - (perf_counter() - started)
        reason = None
        if case["phase"] == "pilot":
            if case["dataset"] not in smoke_summaries:
                reason = "dataset_smoke_failed_or_skipped"
            else:
                projection = projected_runtime(smoke_summaries[case["dataset"]], case["preflight"], resources["runtime_safety_factor"])
                case["projected_runtime_seconds"] = projection
                if projection > resources["max_comparison_wall_seconds"]:
                    reason = "smoke_based_runtime_projection_exceeds_comparison_budget"
                elif projection > remaining:
                    reason = "smoke_based_runtime_projection_exceeds_remaining_study_budget"
        if remaining <= 0:
            reason = "study_wall_budget_exhausted"
        if reason:
            case.update(status="skipped", reason=reason, subprocess_wall_seconds=0.0, run_directory=None)
        else:
            config = ExperimentConfig.from_dict(json.loads(Path(case["config_path"]).read_text()))
            case.update(execute_case(config, Path(case["config_path"]), min(remaining, resources["max_comparison_wall_seconds"]), root / "logs"))
            if case["phase"] == "smoke" and case["status"] == "completed":
                smoke_summaries[case["dataset"]] = json.loads((Path(case["run_directory"]) / "summary.json").read_text())
        completed_cases.append(case)
        write_json(root / "execution.json", completed_cases)
        write_csv(root / "execution.csv", [{k: v for k, v in c.items() if k != "preflight"} for c in completed_cases])
        print(f"{case['case_id']}: {case['status']} ({case['subprocess_wall_seconds']:.3f}s) {case['reason'] or ''}", flush=True)
    summary = collect_outputs(root, completed_cases, scenarios, settings)
    after = snapshot()
    write_json(root / "integrity_after.json", after)
    integrity = {"unchanged": before == after, "files_compared": len(before),
                 "changed_or_added_or_removed": sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))}
    write_json(root / "integrity.json", integrity)
    summary["integrity"] = integrity
    summary["protocol_wall_seconds_through_aggregation"] = perf_counter() - started
    write_json(root / "summary.json", summary)
    if not integrity["unchanged"]:
        raise RuntimeError("Data/core checksum audit failed")
    print(f"Saved {root}; CIC simulations={summary['measured_completed_cic_simulations']}", flush=True)
    return int(summary["failed_or_timed_out_comparisons"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
