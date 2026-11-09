"""Small processed fixtures for runner tests; no repository datasets are written."""

from pathlib import Path

import networkx as nx

from src.data.storage import save_processed_graph
from src.experiments.config import ALGORITHMS
from tests.helpers import metadata_for


def experiment_values(root: Path, *, all_methods: bool = False) -> dict:
    return {
        "dataset": "unit-test-fixture", "processed_directory": str(root / "processed"),
        "rumor_seeds": [10], "k": 1, "p": 0.4, "tie_breaking": "protector-priority",
        "S_opt": 2, "S_eval": 4, "algorithms": list(ALGORITHMS) if all_methods else ["random"],
        "ga_parameters": {"population_size": 4, "max_generations": 2, "crossover_rate": 0.8,
                          "mutation_rate": 0.3, "tournament_size": 2, "elitism_count": 1,
                          "cache_fitness": True} if all_methods else {},
        "pagerank_parameters": {"alpha": 0.85, "tol": 1e-12, "max_iter": 1000} if all_methods else {},
        "candidate_restriction": {"method": "degree", "size": 3} if all_methods else {},
        "limits": {"max_optimization_evaluations": 100, "max_optimization_cic_simulations": 1000,
                   "max_full_greedy_evaluations": 100, "max_full_greedy_cic_simulations": 1000},
        "random_seed": 17, "independent_run_index": 0, "seed_block_size": 1000,
        "output_directory": str(root / "output"), "purpose": "unit_test",
        "save_raw_observations": False,
    }


def processed_fixture(root: Path, *, directed: bool = True) -> nx.Graph:
    graph = nx.DiGraph() if directed else nx.Graph()
    graph.add_edges_from([(10, 20), (20, 30), (40, 30), (30, 50)])
    graph.add_node(90)
    save_processed_graph(graph, metadata_for(graph), root / "processed")
    return graph
