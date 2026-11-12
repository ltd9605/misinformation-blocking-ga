"""Verify main artifacts without selecting seeds or simulating cascades again."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from experiments.analyze_main_experiments import export_numeric
from experiments.reduced_screen_v2 import atomic_json
from src.data import load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT


def verify_preservation(before_path: Path) -> dict:
    """Compare task-start files and historical artifact manifests with disk."""
    before = json.loads(before_path.read_text())
    after = {name: sha256_file(PROJECT_ROOT/name) for name in before}
    changed = [name for name in before if before[name] != after[name]]
    expected_data = {name for name in before if name.startswith("data/")}
    actual_data = {p.relative_to(PROJECT_ROOT).as_posix() for folder in ("raw", "processed")
                   for p in (PROJECT_ROOT/"data"/folder).rglob("*") if p.is_file()}
    prior_reports = {"experiment_protocol_v1": "EXPERIMENT_PROTOCOL_V1.md",
                     "milestone_7_reduced_screen": "MILESTONE_7_REDUCED_SCREEN.md"}
    prior = []
    for campaign in ("pilot_protocol_validation", "pilot_2_calibration", "experiment_protocol_v1",
                     "milestone_7_reduced_screen", "milestone_7_reduced_screen_v2",
                     "cross_scenario_ga_confirmation", "main_experiments_protocol"):
        directory = PROJECT_ROOT/"docs"/campaign
        manifest = json.loads((directory/"artifact_manifest.json").read_text())
        mismatches = [name for name, digest in manifest["files"].items()
                      if not (directory/name).is_file() or sha256_file(directory/name) != digest]
        report = manifest.get("report")
        if report and sha256_file(PROJECT_ROOT/report["path"]) != report["sha256"]:
            mismatches.append(report["path"])
        if campaign in prior_reports and manifest.get("report_sha256"):
            if sha256_file(PROJECT_ROOT/prior_reports[campaign]) != manifest["report_sha256"]:
                mismatches.append(prior_reports[campaign])
        prior.append({"campaign": campaign, "manifest_files_checked": len(manifest["files"]),
                      "mismatches": mismatches, "unchanged": not mismatches})
    topology = []
    for dataset, nodes, edges, directed in (("email-Eu-core", 1005, 24929, True),
                                             ("ego-Facebook", 4039, 88234, False),
                                             ("Wiki-Vote", 7115, 103689, True)):
        graph = load_processed_graph(PROJECT_ROOT/"data"/"processed"/dataset)
        observed = (len(graph), graph.number_of_edges(), graph.is_directed())
        topology.append({"dataset": dataset, "nodes": observed[0], "edges": observed[1],
                         "directed": observed[2], "unchanged": observed == (nodes, edges, directed)})
    result = {"before": before, "after": after, "protected_files_checked": len(before),
              "data_files_checked": len(expected_data), "changed": changed,
              "data_file_set_unchanged": actual_data == expected_data,
              "historical_artifact_manifests": prior, "topology": topology}
    result["passed"] = (not changed and result["data_file_set_unchanged"]
                        and all(p["unchanged"] for p in prior+topology))
    if not result["passed"]:
        raise ValueError(f"Main preservation audit failed: {result}")
    return result


def verify_outputs(root: Path, destination: Path) -> dict:
    """Reaggregate observed counts twice and compare stable numeric exports."""
    state = json.loads((root/"checkpoint.json").read_text())
    if state.get("status") != "completed" or len(state["completed"]) != 432:
        raise ValueError("Finish the frozen matrix before final verification")
    attempts = state["attempts"]
    if len(attempts) != 432 or any(a["status"] != "completed" for a in attempts):
        raise ValueError("Unexpected retry/failure: report partial work before verification")
    final_indices = [i for i, a in enumerate(attempts) if a["kind"] == "final"]
    selection_indices = [i for i, a in enumerate(attempts) if a["kind"] == "selection"]
    if max(selection_indices) >= min(final_indices):
        raise ValueError("All P must be sealed before any final observation")
    stable_names = ("results", "summary_by_scenario", "summary_by_dataset", "method_comparisons",
                    "runtime_summary", "GA_convergence", "Full_Greedy_skipped", "method_status", "final_batches")
    stable_paths = [destination/f"{name}.{suffix}" for name in stable_names for suffix in ("csv", "json")]
    export_numeric(root, destination)
    first = {p.name: sha256_file(p) for p in stable_paths}
    export_numeric(root, destination)
    second = {p.name: sha256_file(p) for p in stable_paths}
    if first != second:
        raise ValueError("Observed numeric exports are not reproducible")
    rows = json.loads((destination/"results.json").read_text())
    if Counter(r["status"] for r in rows) != {"completed": 144}:
        raise ValueError("Expected144 completed primary rows")
    node_sets = {name: set(load_processed_graph(PROJECT_ROOT/"data"/"processed"/name))
                 for name in ("email-Eu-core", "ego-Facebook", "Wiki-Vote")}
    contexts = {}
    for row in rows:
        if not (set(row["rumor_seeds"]) | set(row["protector_seeds"])) <= node_sets[row["dataset"]]:
            raise ValueError("A selected node does not exist in the processed graph")
        key = (row["scenario_id"], row["repetition_index"])
        contexts.setdefault(key, []).append(row)
    for group in contexts.values():
        fields = ("dataset", "rumor_seeds", "k", "p", "tie_breaking",
                  "S_eval_per_batch", "final_batches", "final_batch_seeds")
        if len(group) != 6 or any(any(r[f] != group[0][f] for f in fields) for r in group):
            raise ValueError("Methods in a comparison have different evaluation contexts")
    expected = {"summary_by_scenario": 36, "summary_by_dataset": 18, "method_comparisons": 45,
                "runtime_summary": 18, "GA_convergence": 264, "Full_Greedy_skipped": 24,
                "method_status": 168, "final_batches": 288}
    for name, count in expected.items():
        if len(json.loads((destination/f"{name}.json").read_text())) != count:
            raise ValueError(f"Wrong export count: {name}")
    summary = json.loads((destination/"summary.json").read_text())
    if (summary["actual_evaluator_calls"], summary["actual_CIC_simulations"]) != (2058, 1233000):
        raise ValueError("Actual physical work differs from the reconciled ledger")
    if not json.loads((root/"integrity_after.json").read_text())["unchanged"]:
        raise ValueError("Engine integrity audit failed")
    proof = {"passed": True, "official_resimulations_for_reproducibility": 0,
             "scope": "deterministic tests, seed/hash audit, repeated numeric reaggregation; no full main rerun",
             "bit_identical_numeric_exports": first, "observed_row_counts": {"results": 144, **expected},
             "all_selections_before_any_final": True,
             "same_final_context_within_all_24_comparisons": True,
             "all_stored_R_and_P_are_existing_node_IDs": True,
             "completed_units": len(state["completed"]), "attempts": len(attempts)}
    resume_file = destination/"resume_verification.json"
    if not resume_file.exists() or not json.loads(resume_file.read_text())["passed"]:
        raise ValueError("Run the no-duplicate completed-checkpoint resume check first")
    proof["resume_verification"] = json.loads(resume_file.read_text())
    atomic_json(destination/"reproducibility.json", proof)
    return proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--tests-log", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT/"results/main_experiments_v2")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT/"docs/main_experiments_results")
    args = parser.parse_args(argv)
    preservation = verify_preservation(args.before)
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output/"checksum_verification.json", preservation)
    proof = verify_outputs(args.root, args.output)
    log = args.tests_log.read_text()
    match = re.search(r"Ran (\d+) tests in ([\d.]+)s", log)
    if not match or not log.rstrip().endswith("OK"):
        raise ValueError("Complete successful unittest log required")
    tests = int(match.group(1))
    verification = {"passed": True, "tests_run": tests, "tests_passed": tests,
                    "test_runtime_seconds": float(match.group(2)), "test_log_sha256": sha256_file(args.tests_log),
                    "test_command": ".venv/bin/python -B -m unittest discover -s tests -q",
                    "protected_files_checked": preservation["protected_files_checked"],
                    "data_files_checked": preservation["data_files_checked"],
                    "prior_artifacts_unchanged": True, "topology_unchanged": True,
                    "numeric_reaggregation_bit_identical": proof["passed"], "main_resimulations_for_audit": 0}
    atomic_json(args.output/"verification.json", verification)
    print(json.dumps(verification, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
