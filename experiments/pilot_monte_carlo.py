"""Small Monte Carlo performance/replay check, not official thesis results.

Run with ``python -B -m experiments.pilot_monte_carlo`` from the repo root.
"""

from dataclasses import asdict
import json
import platform
from typing import Any

import networkx as nx

from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic


def _data_hashes() -> dict[str, str]:
    """Fingerprint dataset inputs without writing raw/processed files."""
    return {
        path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
        for path in sorted((PROJECT_ROOT / "data").rglob("*")) if path.is_file()
    }


def _check_deterministic_chain() -> dict[str, Any]:
    """Check two fixed protector configurations with known rumor counts."""
    graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
    common = {
        "rumor_seeds": [0], "propagation_probability": 1.0,
        "number_of_simulations": 5, "base_random_seed": 42,
        "tie_breaking": "protector-priority",
    }
    near = evaluate_cic(graph, protector_seeds=[1], **common)
    far = evaluate_cic(graph, protector_seeds=[3], **common)
    if (
        near.mean_rumor_count != 1 or far.mean_rumor_count != 3
        or near.std_rumor_count != 0 or far.std_rumor_count != 0
    ):
        raise RuntimeError("Deterministic chain Monte Carlo check failed")
    print("PASS chain p=1, R=[0]: P=[1] mean/std=1/0; P=[3] mean/std=3/0")
    return {
        "graph": {"directed": True, "nodes": sorted(graph), "edges": sorted(graph.edges())},
        "common_config": common,
        "near_protector": {"protector_seeds": [1], "result": asdict(near)},
        "far_protector": {"protector_seeds": [3], "result": asdict(far)},
        "passed": True,
    }


def main() -> int:
    """Measure one 100-run batch and verify a second batch replays it exactly."""
    before_hashes = _data_hashes()
    chain_check = _check_deterministic_chain()
    directory = PROJECT_ROOT / "data/processed/email-Eu-core"
    graph = load_processed_graph(directory)
    config = {
        "rumor_seeds": [0],
        "protector_seeds": [1],
        "propagation_probability": 0.05,
        "number_of_simulations": 100,
        "base_random_seed": 42,
        "tie_breaking": "protector-priority",
    }
    result = evaluate_cic(graph, **config)
    replay = evaluate_cic(graph, **config)
    if result != replay:
        raise RuntimeError("Monte Carlo replay changed statistics or raw observations")
    after_hashes = _data_hashes()
    if before_hashes != after_hashes:
        raise RuntimeError("Dataset files changed during the Monte Carlo pilot")

    report = {
        "purpose": "implementation_and_performance_validation_only",
        "official_thesis_result": False,
        "dataset": "email-Eu-core",
        "processed_directory": directory.relative_to(PROJECT_ROOT).as_posix(),
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "environment": {
            "python": platform.python_version(), "networkx": nx.__version__,
            "platform": platform.platform(), "machine": platform.machine(),
        },
        "config": config,
        "seed_schedule": "simulation_seed[i] = base_random_seed + i; i = 0..S-1",
        "rumor_standard_deviation": {"kind": "population", "ddof": 0},
        "result": asdict(result),
        "replay_runtime_seconds": replay.runtime_seconds,
        "runtime_scope": "one S-run evaluation including aggregation, excluding dataset loading and file I/O",
        "repeatability_verified_excluding_runtime": True,
        "data_sha256_before": before_hashes,
        "data_sha256_after": after_hashes,
        "source_data_unchanged": True,
        "deterministic_chain_check": chain_check,
    }
    output = PROJECT_ROOT / "results/pilots/monte_carlo_email_eu_core.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print("PILOT ONLY: implementation/performance validation; not an official thesis result.")
    print(f"email-Eu-core: R={config['rumor_seeds']}, P={config['protector_seeds']}, "
          f"p={config['propagation_probability']}, S={result.number_of_simulations}, "
          f"base_seed={result.base_random_seed}, tie={result.tie_breaking}")
    print(f"Rumor mean={result.mean_rumor_count:.6f}, population std={result.std_rumor_count:.6f}, "
          f"min={result.min_rumor_count}, max={result.max_rumor_count}")
    print(f"Protector mean={result.mean_protector_count:.6f}, inactive mean={result.mean_inactive_count:.6f}")
    print(f"First S-run batch runtime={result.runtime_seconds:.6f} seconds; replay statistics/observations match.")
    print(f"Saved configuration, raw observations and checks: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
