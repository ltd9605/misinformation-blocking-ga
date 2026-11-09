"""Hand checks and a small CIC pilot, excluded from official thesis results.

Run from the repository root with ``python -B -m experiments.pilot_cic``.
"""

from dataclasses import asdict
import json
import platform
from time import perf_counter
from typing import Any

import networkx as nx

from src.data import graph_statistics, load_processed_graph
from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT
from src.diffusion import CICResult, simulate_cic


def _result_dict(result: CICResult) -> dict[str, Any]:
    """Serialize results from the integer-labeled graphs in this pilot."""
    return {
        "rumor_nodes": sorted(result.rumor_nodes),
        "protector_nodes": sorted(result.protector_nodes),
        "inactive_nodes": sorted(result.inactive_nodes),
        "rumor_count": result.rumor_count,
        "protector_count": result.protector_count,
        "inactive_count": result.inactive_count,
        "steps": result.steps,
        "activation_layers": [
            {"rumor_nodes": sorted(layer.rumor_nodes), "protector_nodes": sorted(layer.protector_nodes)}
            for layer in result.activation_layers
        ],
    }


def _data_hashes() -> dict[str, str]:
    """Fingerprint all raw/processed inputs without writing dataset files."""
    return {
        path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
        for path in sorted((PROJECT_ROOT / "data").rglob("*")) if path.is_file()
    }


def _check_small_graphs() -> list[dict[str, Any]]:
    """Run ten cases with explicit final states that can be checked by hand."""
    chain = nx.DiGraph([(0, 1), (1, 2)])
    separate = nx.DiGraph([(0, 1), (2, 3)])
    rumor_first = nx.DiGraph([(0, 3), (9, 8), (8, 3), (3, 4)])
    protector_first = nx.DiGraph([(0, 1), (1, 3), (9, 3), (3, 4)])
    tie = nx.DiGraph([(0, 2), (1, 2), (2, 3)])
    undirected = nx.path_graph(5)
    isolated = nx.DiGraph([(0, 1)])
    isolated.add_nodes_from([9, 10])
    examples = (
        ("only_rumor", chain, [0], [], 1.0, "protector-priority", {0, 1, 2}, set(), 2),
        ("only_protector", chain, [], [0], 1.0, "protector-priority", set(), {0, 1, 2}, 2),
        ("separate_cascades", separate, [0], [2], 1.0, "protector-priority", {0, 1}, {2, 3}, 1),
        ("rumor_arrives_first", rumor_first, [0], [9], 1.0, "protector-priority", {0, 3, 4}, {8, 9}, 2),
        ("protector_arrives_first", protector_first, [0], [9], 1.0, "rumor-priority", {0, 1}, {3, 4, 9}, 2),
        ("tie_protector_priority", tie, [0], [1], 1.0, "protector-priority", {0}, {1, 2, 3}, 2),
        ("tie_rumor_priority", tie, [0], [1], 1.0, "rumor-priority", {0, 2, 3}, {1}, 2),
        ("undirected_chain", undirected, [0], [4], 1.0, "protector-priority", {0, 1}, {2, 3, 4}, 2),
        ("isolated_seeds", isolated, [9], [10], 1.0, "protector-priority", {9}, {10}, 0),
        ("p_zero", tie, [0], [1], 0.0, "protector-priority", {0}, {1}, 0),
    )
    records = []
    for name, graph, rumor, protector, p, rule, expected_rumor, expected_protector, steps in examples:
        config = {
            "rumor_seeds": rumor,
            "protector_seeds": protector,
            "propagation_probability": p,
            "tie_breaking": rule,
            "random_seed": 42,
        }
        result = simulate_cic(graph, **config)
        expected_inactive = set(graph) - expected_rumor - expected_protector
        if (
            result.rumor_nodes != expected_rumor or result.protector_nodes != expected_protector
            or result.inactive_nodes != expected_inactive or result.steps != steps
        ):
            raise RuntimeError(f"Hand-checkable example failed: {name}: {_result_dict(result)}")
        records.append({
            "name": name,
            "graph": {"directed": graph.is_directed(), "nodes": sorted(graph), "edges": sorted(graph.edges())},
            "config": config,
            "expected": {
                "rumor_nodes": sorted(expected_rumor), "protector_nodes": sorted(expected_protector),
                "inactive_nodes": sorted(expected_inactive), "steps": steps,
            },
            "result": _result_dict(result),
            "passed": True,
        })
        print(f"PASS {name}: R={sorted(result.rumor_nodes)}, P={sorted(result.protector_nodes)}, "
              f"inactive={sorted(result.inactive_nodes)}, steps={result.steps}")
    return records


def main() -> int:
    """Check tiny graphs, repeatability, insertion order and input fingerprints."""
    before_hashes = _data_hashes()
    manual_checks = _check_small_graphs()
    directory = PROJECT_ROOT / "data/processed/email-Eu-core"
    graph = load_processed_graph(directory)
    config = {
        "rumor_seeds": [0],
        "protector_seeds": [1],
        "propagation_probability": 0.05,
        "tie_breaking": "protector-priority",
        "random_seed": 42,
    }
    started = perf_counter()
    result = simulate_cic(graph, **config)
    runtime = perf_counter() - started
    if result != simulate_cic(graph, **config):
        raise RuntimeError("CIC pilot is not reproducible with the same configuration")
    reverse_order = nx.DiGraph()
    reverse_order.add_nodes_from(reversed(list(graph)))
    reverse_order.add_edges_from(reversed(list(graph.edges())))
    if result != simulate_cic(reverse_order, **config):
        raise RuntimeError("CIC pilot depends on graph insertion order")
    after_hashes = _data_hashes()
    if before_hashes != after_hashes:
        raise RuntimeError("Raw/processed dataset files changed during the CIC pilot")

    report = {
        "purpose": "implementation_validation_only",
        "official_thesis_result": False,
        "model": "Competitive Independent Cascade",
        "dataset": "email-Eu-core",
        "processed_directory": directory.relative_to(PROJECT_ROOT).as_posix(),
        "data_sha256_before": before_hashes,
        "data_sha256_after": after_hashes,
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "environment": {
            "python": platform.python_version(), "networkx": nx.__version__,
            "platform": platform.platform(), "machine": platform.machine(),
        },
        "config": config,
        "result": _result_dict(result),
        "diagnostic_runtime_seconds": runtime,
        "repeatability_verified": True,
        "graph_insertion_order_independence_verified": True,
        "source_data_unchanged": True,
        "manual_checks": manual_checks,
    }
    output = PROJECT_ROOT / "results/pilots/cic_email_eu_core.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print("PILOT ONLY: implementation validation; not an official thesis result.")
    print(f"email-Eu-core: R={config['rumor_seeds']}, P={config['protector_seeds']}, "
          f"p={config['propagation_probability']}, random_seed={config['random_seed']}, "
          f"tie={config['tie_breaking']}, rumor={result.rumor_count}, "
          f"protector={result.protector_count}, inactive={result.inactive_count}, steps={result.steps}")
    print(f"Saved configuration, results and checks: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
