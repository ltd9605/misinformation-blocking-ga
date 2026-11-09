"""Small IC implementation checks; outputs are not official thesis results.

Run from the repository root with ``python -B -m experiments.pilot_ic``.
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
from src.diffusion import ICResult, simulate_ic


def _result_dict(result: ICResult) -> dict[str, Any]:
    """Serialize the integer-labeled graphs used by this pilot."""
    return {
        "active_nodes": sorted(result.active_nodes),
        "active_count": result.active_count,
        "steps": result.steps,
        "activation_layers": [sorted(layer) for layer in result.activation_layers],
    }


def _check_small_graphs() -> list[dict[str, Any]]:
    """Run examples whose complete activation layers can be checked by hand."""
    directed = nx.DiGraph([(0, 1), (1, 2)])
    undirected = nx.Graph([(0, 1), (1, 2)])
    isolated = directed.copy()
    isolated.add_node(9)
    examples = (
        ("directed_chain_forward", directed, [0], 1.0, [[0], [1], [2]]),
        ("directed_chain_reverse", directed, [2], 1.0, [[2]]),
        ("undirected_chain_center", undirected, [1], 1.0, [[1], [0, 2]]),
        ("isolated_seed", isolated, [9], 1.0, [[9]]),
        ("p_zero", directed, [0], 0.0, [[0]]),
    )
    records = []
    for name, graph, seeds, probability, expected_layers in examples:
        result = simulate_ic(graph, seeds, probability, random_seed=42)
        serialized = _result_dict(result)
        expected_nodes = {node for layer in expected_layers for node in layer}
        if (
            serialized["activation_layers"] != expected_layers
            or result.active_nodes != expected_nodes
            or result.active_count != len(expected_nodes)
            or result.steps != len(expected_layers) - 1
        ):
            raise RuntimeError(f"Hand-checkable example failed: {name}: {serialized}")
        records.append({
            "name": name,
            "directed": graph.is_directed(),
            "nodes": sorted(graph),
            "edges": sorted(graph.edges()),
            "config": {
                "seed_nodes": seeds,
                "propagation_probability": probability,
                "random_seed": 42,
            },
            "expected_layers": expected_layers,
            "result": serialized,
            "passed": True,
        })
        print(f"PASS {name}: layers={expected_layers}, steps={result.steps}")
    return records


def main() -> int:
    """Validate tiny examples and one reproducible run on processed email data."""
    manual_checks = _check_small_graphs()
    directory = PROJECT_ROOT / "data/processed/email-Eu-core"
    artifacts = ("nodes.csv", "edges.csv", "metadata.json")
    before_hashes = {name: sha256_file(directory / name) for name in artifacts}
    graph = load_processed_graph(directory)
    config = {"seed_nodes": [0], "propagation_probability": 0.05, "random_seed": 42}
    started = perf_counter()
    result = simulate_ic(graph, **config)
    runtime = perf_counter() - started
    if result != simulate_ic(graph, **config):
        raise RuntimeError("Email pilot is not reproducible with the same random seed")
    after_hashes = {name: sha256_file(directory / name) for name in artifacts}
    if before_hashes != after_hashes:
        raise RuntimeError("Processed email artifacts changed during the pilot")

    report = {
        "purpose": "implementation_validation_only",
        "official_thesis_result": False,
        "model": "Independent Cascade",
        "dataset": "email-Eu-core",
        "processed_directory": directory.relative_to(PROJECT_ROOT).as_posix(),
        "source_artifact_sha256": before_hashes,
        "graph": {**asdict(graph_statistics(graph)), "directed": graph.is_directed()},
        "environment": {
            "python": platform.python_version(),
            "networkx": nx.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "config": config,
        "result": _result_dict(result),
        "diagnostic_runtime_seconds": runtime,
        "repeatability_verified": True,
        "source_artifacts_unchanged": True,
        "manual_checks": manual_checks,
    }
    output = PROJECT_ROOT / "results/pilots/ic_email_eu_core.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("PILOT ONLY: implementation validation; not an official thesis result.")
    print(f"email-Eu-core: seeds={config['seed_nodes']}, p={config['propagation_probability']}, "
          f"random_seed={config['random_seed']}, active={result.active_count}, steps={result.steps}")
    print(f"Saved configuration, results and checks: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
