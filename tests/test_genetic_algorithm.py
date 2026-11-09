"""GA evolution, fixed-seed fitness/cache policy, elite invariants and replay."""

from copy import deepcopy
from dataclasses import replace
import json
import os
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

import networkx as nx

from src.algorithms import make_seed_plan, select_genetic_algorithm
from src.algorithms.ga_operators import elite_indices
from src.data.specs import PROJECT_ROOT
from src.evaluation import evaluate_cic


def run_ga(graph, rumor=(0,), k=1, p=1, simulations=3, **overrides):
    parameters = dict(population_size=6, max_generations=3, crossover_rate=0.8,
                      mutation_rate=0.3, tournament_size=3, elitism_count=1,
                      random_seed=42, tie_breaking="protector-priority", fitness_base_random_seed=100)
    parameters.update(overrides)
    return select_genetic_algorithm(graph, rumor, k, p, simulations, **parameters)


class GeneticAlgorithmTests(unittest.TestCase):
    def test_seed_domains_are_reproducible_and_holdout_block_is_disjoint(self) -> None:
        first = make_seed_plan(42, 20)
        self.assertEqual(first, make_seed_plan(42, 20))
        self.assertNotEqual(first.operators_seed, first.fitness_base_random_seed)
        self.assertFalse(set(range(first.fitness_base_random_seed, first.fitness_seed_stop_exclusive)) &
                         set(range(first.independent_evaluation_base_random_seed,
                                   first.independent_evaluation_base_random_seed + 100)))
        self.assertNotEqual(first, make_seed_plan(43, 20))

    def test_explicit_fitness_base_does_not_change_operator_stream(self) -> None:
        a, b = make_seed_plan(42, 20, 100), make_seed_plan(42, 20, 200)
        self.assertEqual(a.operators_seed, b.operators_seed)
        self.assertEqual((a.fitness_base_random_seed, a.independent_evaluation_base_random_seed), (100, 120))
        self.assertEqual(b.independent_evaluation_base_random_seed, 220)

    def test_directed_chain_matches_hand_checked_optimum(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        result = run_ga(graph)
        self.assertEqual(result.best_protector_nodes, {1})
        self.assertEqual(result.best_estimated_fitness, 1)
        self.assertEqual(result.generations_run, 3)

    def test_undirected_chain_matches_hand_checked_minimum(self) -> None:
        result = run_ga(nx.path_graph(4))
        self.assertEqual(result.best_estimated_fitness, 1)
        self.assertEqual(result.best_protector_nodes, {1})

    def test_all_generations_and_individuals_preserve_constraints(self) -> None:
        graph = nx.DiGraph([(3, 17), (17, 90), (90, 8000), (60000, 17)])
        result = run_ga(graph, rumor=[3], k=2)
        for generation in result.history:
            self.assertEqual(len(generation.population), 6)
            self.assertEqual(len(generation.fitness_values), 6)
            for individual in generation.population:
                self.assertEqual(len(individual), 2)
                self.assertTrue(individual <= set(graph) - {3})
        self.assertTrue(result.best_protector_nodes <= {17, 90, 8000, 60000})

    def test_stop_is_exactly_G_transitions_with_initial_generation_zero(self) -> None:
        result = run_ga(nx.path_graph(4), max_generations=5)
        self.assertEqual(result.generations_run, 5)
        self.assertEqual([record.generation for record in result.history], list(range(6)))

    def test_zero_generations_still_evaluates_initial_population(self) -> None:
        result = run_ga(nx.path_graph(4), max_generations=0)
        self.assertEqual(result.generations_run, 0)
        self.assertEqual(len(result.history), 1)
        self.assertGreater(result.evaluation_count, 0)
        self.assertEqual(result.fitness_request_count, 6)

    def test_k_zero_keeps_N_empty_individuals_and_evaluates_empty_P_once(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        result = run_ga(graph, k=0)
        self.assertEqual(result.best_protector_nodes, frozenset())
        self.assertEqual(result.best_estimated_fitness, 4)
        self.assertEqual(result.evaluation_count, 1)
        self.assertEqual(result.cic_simulation_count, 3)
        for generation in result.history:
            self.assertEqual(generation.population, (frozenset(),) * 6)
            self.assertEqual(generation.unique_individuals, 1)

    def test_k_equals_eligible_count_is_valid_with_repeated_genotypes(self) -> None:
        result = run_ga(nx.path_graph(4), k=3)
        self.assertEqual(result.best_protector_nodes, {1, 2, 3})
        self.assertEqual(result.evaluation_count, 1)
        self.assertTrue(all(row.unique_individuals == 1 for row in result.history))

    def test_full_elitism_keeps_population_and_fitness_without_child_evaluations(self) -> None:
        result = run_ga(nx.path_graph(4), elitism_count=6, cache_fitness=False)
        self.assertEqual(result.evaluation_count, 6)
        self.assertEqual(result.elite_fitness_reuse_count, 18)
        initial = sorted(zip(result.history[0].fitness_values, result.history[0].population),
                         key=lambda item: (item[0], tuple(sorted(item[1]))))
        for generation in result.history[1:]:
            self.assertEqual(list(zip(generation.fitness_values, generation.population)), initial)
            self.assertEqual(generation.evaluations_this_generation, 0)

    def test_elite_genotype_and_fitness_are_copied_verbatim_each_generation(self) -> None:
        graph = nx.gnp_random_graph(10, 0.3, seed=7, directed=True)
        result = run_ga(graph, p=0.4, k=2, elitism_count=2)
        for previous, current in zip(result.history, result.history[1:]):
            slots = elite_indices(previous.population, previous.fitness_values, 2)
            self.assertEqual(current.population[:2], tuple(previous.population[i] for i in slots))
            self.assertEqual(current.fitness_values[:2], tuple(previous.fitness_values[i] for i in slots))
            self.assertLessEqual(current.best_fitness, previous.best_fitness)

    def test_without_elites_global_best_is_retained_if_current_generation_worsens(self) -> None:
        initial = (frozenset({1}), frozenset({2}))
        with patch("src.algorithms.genetic_algorithm.initialize_population", return_value=initial), \
             patch("src.algorithms.genetic_algorithm.mutate_individual", return_value=frozenset({3})):
            result = run_ga(nx.DiGraph([(0, 1), (1, 2), (2, 3)]), population_size=2,
                            tournament_size=2, elitism_count=0, max_generations=1,
                            crossover_rate=0, mutation_rate=1)
        self.assertEqual([row.best_fitness for row in result.history], [1, 3])
        self.assertEqual([row.best_so_far_fitness for row in result.history], [1, 1])
        self.assertEqual(result.best_protector_nodes, {1})
        self.assertEqual(result.best_estimated_fitness, 1)

    def test_every_cache_miss_uses_the_verified_evaluator_with_fixed_context(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        with patch("src.algorithms.genetic_algorithm.evaluate_cic", wraps=evaluate_cic) as evaluator:
            result = run_ga(graph, p=0.4)
        self.assertEqual(evaluator.call_count, result.evaluation_count)
        self.assertEqual(len(result.fitness_evaluations), result.evaluation_count)
        for call in evaluator.call_args_list:
            self.assertIs(call.args[0], graph)
            self.assertEqual(call.args[1], {0})
            self.assertEqual(call.args[3:], (0.4, 3))
            self.assertEqual(call.kwargs, {"base_random_seed": 100, "tie_breaking": "protector-priority"})
        self.assertEqual(result.cic_simulation_count, evaluator.call_count * 3)

    def test_cache_hits_are_not_counted_as_new_MC_evaluations(self) -> None:
        result = run_ga(nx.path_graph(4), k=0)
        expected_requests = 6 + 3 * 5
        self.assertEqual(result.fitness_request_count, expected_requests)
        self.assertEqual(result.cache_hit_count, expected_requests - 1)
        self.assertEqual(sum(row.evaluations_this_generation for row in result.history), 1)
        self.assertEqual(result.elite_fitness_reuse_count, 3)

    def test_uncached_mode_reevaluates_children_on_same_schedule(self) -> None:
        result = run_ga(nx.path_graph(4), k=0, cache_fitness=False)
        self.assertEqual(result.evaluation_count, 6 + 3 * 5)
        self.assertEqual(result.cache_hit_count, 0)
        self.assertEqual(result.uncached_evaluation_upper_bound, result.evaluation_count)

    def test_request_cache_and_elite_counts_account_for_every_population_slot(self) -> None:
        result = run_ga(nx.path_graph(5), k=2)
        self.assertEqual(result.fitness_request_count + result.elite_fitness_reuse_count, 6 * 4)
        self.assertEqual(result.fitness_request_count, result.evaluation_count + result.cache_hit_count)
        self.assertLessEqual(result.evaluation_count, result.cached_evaluation_upper_bound)
        self.assertEqual(sum(row.evaluations_this_generation for row in result.history), result.evaluation_count)
        self.assertEqual(sum(row.cache_hits_this_generation for row in result.history), result.cache_hit_count)

    def test_convergence_statistics_match_the_logged_population(self) -> None:
        result = run_ga(nx.gnp_random_graph(8, 0.3, seed=7, directed=True), k=2, p=0.4)
        for row in result.history:
            self.assertEqual(row.best_fitness, min(row.fitness_values))
            self.assertEqual(row.worst_fitness, max(row.fitness_values))
            self.assertAlmostEqual(row.mean_fitness, sum(row.fitness_values) / len(row.fitness_values))
            self.assertEqual(row.unique_individuals, len(set(row.population)))

    def test_cache_toggle_preserves_evolution_with_same_seeds(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=13, directed=True)
        cached = run_ga(graph, p=0.4, k=2)
        uncached = run_ga(graph, p=0.4, k=2, cache_fitness=False)
        self.assertEqual(cached.best_protector_nodes, uncached.best_protector_nodes)
        for a, b in zip(cached.history, uncached.history):
            self.assertEqual(a.population, b.population)
            self.assertEqual(a.fitness_values, b.fitness_values)
        self.assertLessEqual(cached.evaluation_count, uncached.evaluation_count)

    def test_cache_is_not_reused_between_calls_or_changed_model_contexts(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        with patch("src.algorithms.genetic_algorithm.evaluate_cic", wraps=evaluate_cic) as evaluator:
            zero = run_ga(graph, k=0, p=0)
            one = run_ga(graph, k=0, p=1)
        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual(zero.best_estimated_fitness, 1)
        self.assertEqual(one.best_estimated_fitness, 4)

    def test_recorded_fitness_can_be_replayed_directly(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=7, directed=True)
        result = run_ga(graph, p=0.4, k=2)
        for record in result.fitness_evaluations:
            direct = evaluate_cic(graph, result.rumor_seeds, record.protector_nodes, 0.4, 3,
                                  base_random_seed=result.seeds.fitness_base_random_seed,
                                  tie_breaking=result.parameters.tie_breaking)
            self.assertEqual(direct.mean_rumor_count, record.mean_rumor_count)
            self.assertEqual(direct.std_rumor_count, record.std_rumor_count)

    def test_reproducibility_includes_population_and_fitness_history(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=7, directed=True)
        self.assertEqual(run_ga(graph, p=0.4, k=2), run_ga(graph, p=0.4, k=2))

    def test_reverse_graph_and_seed_insertion_order_preserves_results(self) -> None:
        graph = nx.gnp_random_graph(8, 0.3, seed=7, directed=True)
        reverse = nx.DiGraph()
        reverse.add_nodes_from(reversed(list(graph)))
        reverse.add_edges_from(reversed(list(graph.edges())))
        self.assertEqual(run_ga(graph, rumor=[0, 7], p=0.4, k=2),
                         run_ga(reverse, rumor=iter([7, 0]), p=0.4, k=2))

    def test_reproducibility_across_process_hash_seeds(self) -> None:
        script = """
import json
import networkx as nx
from src.algorithms import select_genetic_algorithm
g = nx.DiGraph()
g.add_nodes_from({'r','a','b','c','d'})
g.add_edges_from({('r','a'),('r','b'),('a','c'),('b','d'),('c','d')})
r = select_genetic_algorithm(g, ['r'], 1, 0.5, 3, population_size=4,
    max_generations=2, crossover_rate=0.8, mutation_rate=0.3,
    tournament_size=2, elitism_count=1, random_seed=42,
    tie_breaking='protector-priority')
print(json.dumps([sorted(r.best_protector_nodes), r.best_estimated_fitness,
    r.evaluation_count, [[sorted(x) for x in h.population] for h in r.history],
    [h.fitness_values for h in r.history]]))
"""
        output = []
        for hash_seed in ("1", "919"):
            completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=PROJECT_ROOT,
                                       env={**os.environ, "PYTHONHASHSEED": hash_seed},
                                       capture_output=True, text=True, check=True)
            output.append(json.loads(completed.stdout))
        self.assertEqual(output[0], output[1])

    def test_global_rng_and_graph_attributes_are_unchanged(self) -> None:
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 3)])
        graph.graph["name"] = "input"
        graph.nodes[2]["state"] = "inactive"
        graph.edges[0, 1]["weight"] = 0
        before = deepcopy(graph)
        state = random.getstate()
        run_ga(nx.freeze(graph), p=0.4)
        self.assertEqual(state, random.getstate())
        self.assertTrue(nx.utils.graphs_equal(before, graph))

    def test_corrupt_operator_output_is_rejected_before_fitness(self) -> None:
        with patch("src.algorithms.genetic_algorithm.mutate_individual", return_value=frozenset({0})):
            with self.assertRaisesRegex(ValueError, "eligible"):
                run_ga(nx.path_graph(4), mutation_rate=1)

    def test_rates_zero_clone_and_rates_one_still_preserve_constraints(self) -> None:
        for rate in (0, 1):
            result = run_ga(nx.path_graph(5), k=2, crossover_rate=rate, mutation_rate=rate)
            for generation in result.history:
                self.assertTrue(all(len(x) == 2 and 0 not in x for x in generation.population))

    def test_empty_graph_empty_rumor_and_zero_budget(self) -> None:
        result = run_ga(nx.Graph(), rumor=[], k=0, population_size=1, tournament_size=1, elitism_count=0)
        self.assertEqual(result.best_estimated_fitness, 0)
        self.assertEqual(result.evaluation_count, 1)

    def test_invalid_budgets_seeds_and_graphs_are_rejected(self) -> None:
        for k in (-1, True, 4):
            with self.assertRaises((TypeError, ValueError)):
                run_ga(nx.path_graph(4), k=k)
        with self.assertRaisesRegex(ValueError, "exist"):
            run_ga(nx.path_graph(4), rumor=[99])
        for graph in (None, [], nx.MultiGraph(), nx.MultiDiGraph()):
            with self.assertRaises(TypeError):
                run_ga(graph)

    def test_invalid_GA_parameters_are_rejected(self) -> None:
        invalid = (
            {"population_size": 0}, {"population_size": True}, {"max_generations": -1},
            {"max_generations": True}, {"tournament_size": 0}, {"tournament_size": 7},
            {"elitism_count": -1}, {"elitism_count": 7}, {"crossover_rate": True},
            {"crossover_rate": -0.1}, {"mutation_rate": 1.1}, {"mutation_rate": float("nan")},
            {"random_seed": -1}, {"random_seed": None}, {"fitness_base_random_seed": -1},
            {"cache_fitness": 1}, {"tie_breaking": "first-visited"},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                run_ga(nx.path_graph(4), **kwargs)
        for p, simulations in ((True, 3), (float("nan"), 3), (0.5, 0), (0.5, True)):
            with self.assertRaises((TypeError, ValueError)):
                run_ga(nx.path_graph(4), p=p, simulations=simulations)

    def test_runtime_is_logged_and_excluded_from_value_equality(self) -> None:
        result = run_ga(nx.path_graph(4))
        self.assertEqual(result, replace(result, optimization_runtime_seconds=999))
        self.assertGreaterEqual(result.optimization_runtime_seconds, result.evaluator_runtime_seconds)
        self.assertEqual(sorted(h.elapsed_optimization_seconds for h in result.history),
                         [h.elapsed_optimization_seconds for h in result.history])

    def test_evaluator_failures_do_not_return_a_partial_GA_result(self) -> None:
        failure = RuntimeError("test evaluator failure")
        with patch("src.algorithms.genetic_algorithm.evaluate_cic", side_effect=failure):
            with self.assertRaises(RuntimeError) as context:
                run_ga(nx.path_graph(4))
        self.assertIs(context.exception, failure)
