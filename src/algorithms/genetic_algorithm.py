"""Genetic optimization of k-node protector sets using fixed-seed CIC fitness."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
import hashlib
from math import comb, fsum
from numbers import Real
from random import Random
from statistics import fmean
from time import perf_counter

import networkx as nx

from src.diffusion import TieBreakingRule
from src.evaluation import evaluate_cic
from .baselines import _candidates
from .greedy import _validate_settings
from .ga_operators import (
    Individual, _integer, elite_indices, individual_key, initialize_population,
    mutate_individual, repair_individual, set_crossover, tournament_selection,
    validate_individual, validate_population,
)


@dataclass(frozen=True)
class GAParameters:
    """Optimization inputs; number_of_simulations is S_opt, not held-out S_eval."""

    k: int
    propagation_probability: float
    number_of_simulations: int
    population_size: int
    max_generations: int
    crossover_rate: float
    mutation_rate: float
    tournament_size: int
    elitism_count: int
    random_seed: int
    tie_breaking: TieBreakingRule
    cache_fitness: bool


@dataclass(frozen=True)
class GASeedPlan:
    """Private operator seed and disjoint optimization/held-out CIC seed blocks."""

    master_seed: int
    operators_seed: int
    fitness_base_random_seed: int
    fitness_seed_stop_exclusive: int
    independent_evaluation_base_random_seed: int


def make_seed_plan(random_seed: int, number_of_simulations: int,
                   fitness_base_random_seed: int | None = None) -> GASeedPlan:
    """Domain-separate operators/fitness; held-out block starts after S_opt seeds."""
    _integer("random_seed", random_seed, 0)
    _integer("number_of_simulations", number_of_simulations, 1)
    def derive(domain: str) -> int:
        digest = hashlib.sha256(f"misinformation-ga-v1:{domain}:{random_seed}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")
    if fitness_base_random_seed is None:
        fitness_base_random_seed = derive("fitness")
    _integer("fitness_base_random_seed", fitness_base_random_seed, 0)
    stop = fitness_base_random_seed + number_of_simulations
    return GASeedPlan(random_seed, derive("operators"), fitness_base_random_seed, stop, stop)


@dataclass(frozen=True)
class GAFitnessEvaluation:
    """One actual evaluator call; reused cache hits/elite carries add no records."""

    evaluation_index: int
    generation: int
    protector_nodes: Individual
    mean_rumor_count: float
    std_rumor_count: float
    mean_protector_count: float
    mean_inactive_count: float
    runtime_seconds: float = field(compare=False)


@dataclass(frozen=True)
class GAGeneration:
    """Generation 0 is initialization; each later record follows one transition."""

    generation: int
    best_protector_nodes: Individual
    best_fitness: float
    best_so_far_fitness: float
    mean_fitness: float
    worst_fitness: float
    unique_individuals: int
    population: tuple[Individual, ...]
    fitness_values: tuple[float, ...]
    elite_count_carried: int
    evaluations_this_generation: int
    cumulative_evaluations: int
    cache_hits_this_generation: int
    cumulative_cache_hits: int
    elapsed_optimization_seconds: float = field(compare=False)


@dataclass(frozen=True)
class GeneticAlgorithmResult:
    """Optimization result, not an independent or official quality estimate."""

    best_protector_nodes: Individual
    best_estimated_fitness: float
    generations_run: int
    history: tuple[GAGeneration, ...]
    fitness_evaluations: tuple[GAFitnessEvaluation, ...]
    evaluation_count: int
    cic_simulation_count: int
    fitness_request_count: int
    cache_hit_count: int
    elite_fitness_reuse_count: int
    uncached_evaluation_upper_bound: int
    cached_evaluation_upper_bound: int
    rumor_seeds: frozenset[Hashable]
    eligible_nodes: frozenset[Hashable]
    parameters: GAParameters
    seeds: GASeedPlan
    evaluator_runtime_seconds: float = field(compare=False)
    optimization_runtime_seconds: float = field(compare=False)


def select_genetic_algorithm(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
    propagation_probability: float, number_of_simulations: int,
    *, population_size: int, max_generations: int, crossover_rate: float,
    mutation_rate: float, tournament_size: int, elitism_count: int,
    random_seed: int, tie_breaking: TieBreakingRule | str,
    fitness_base_random_seed: int | None = None, cache_fitness: bool = True,
) -> GeneticAlgorithmResult:
    """Minimize fixed-schedule Monte Carlo mean rumor count with a set-based GA.

    Every new fitness evaluation calls evaluate_cic unchanged with the same
    graph/R/p/S/tie/base seed. The cache is local to this call and keyed by the
    frozenset genotype: all other fitness context stays fixed. No cross-run or
    fresh-seed reuse is performed. cache_fitness=False re-evaluates non-elite
    fitness requests on this same schedule; it does not resample the objective.

    Elites carry both genotype and fitness unchanged. Remaining slots use two
    tournaments, probabilistic set crossover (otherwise clone first parent),
    probabilistic one-gene mutation, then repair/invariant checks. Population
    slots may share genotypes. All sampling uses a private domain-separated RNG.

    Generation 0 evaluates initialization. Run exactly max_generations further
    transitions, including for k=0 or full elitism. Report both generation-best
    and best-so-far: without elites generation-best can worsen. Return the best
    ever seen, ties by canonical genotype. No automatic early stop is used.

    Returned fitness was used for optimization and may overfit its fixed seeds.
    An independent evaluator call must use fresh seeds (the returned seed plan
    gives a disjoint base) and must not feed back into this selection. This
    function does not run that evaluation or an experiment runner.
    """
    started = perf_counter()
    rumor = frozenset(rumor_seeds)
    _, eligible = _candidates(graph, rumor, k)
    _integer("population_size", population_size, 1)
    _integer("max_generations", max_generations, 0)
    _integer("tournament_size", tournament_size, 1)
    _integer("elitism_count", elitism_count, 0)
    if tournament_size > population_size or elitism_count > population_size:
        raise ValueError("Tournament and elite counts cannot exceed population_size")
    for name, value in (("crossover_rate", crossover_rate), ("mutation_rate", mutation_rate)):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a real number")
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    if type(cache_fitness) is not bool:
        raise TypeError("cache_fitness must be a boolean")
    seeds = make_seed_plan(random_seed, number_of_simulations, fitness_base_random_seed)
    rule = _validate_settings(propagation_probability, seeds.fitness_base_random_seed, tie_breaking)
    parameters = GAParameters(k, propagation_probability, number_of_simulations, population_size,
                              max_generations, crossover_rate, mutation_rate, tournament_size,
                              elitism_count, random_seed, rule, cache_fitness)
    rng = Random(seeds.operators_seed)
    eligible_set = frozenset(eligible)
    cache: dict[Individual, GAFitnessEvaluation] = {}
    evaluations: list[GAFitnessEvaluation] = []
    requests = cache_hits = 0

    def score(individual: Individual, generation: int) -> GAFitnessEvaluation:
        nonlocal requests, cache_hits
        validate_individual(individual, eligible_set, k)
        requests += 1
        if cache_fitness and individual in cache:
            cache_hits += 1
            return cache[individual]
        estimate = evaluate_cic(
            graph, rumor, individual, propagation_probability, number_of_simulations,
            base_random_seed=seeds.fitness_base_random_seed, tie_breaking=rule,
        )
        fitness = GAFitnessEvaluation(len(evaluations), generation, individual,
                                      estimate.mean_rumor_count, estimate.std_rumor_count,
                                      estimate.mean_protector_count, estimate.mean_inactive_count,
                                      estimate.runtime_seconds)
        evaluations.append(fitness)
        if cache_fitness:
            cache[individual] = fitness
        return fitness

    population = initialize_population(eligible, k, population_size, rng=rng)
    fitness = tuple(score(individual, 0) for individual in population)
    history: list[GAGeneration] = []
    best_nodes: Individual = frozenset()
    best_value = float("inf")
    previous_calls = previous_hits = 0

    def record(generation: int) -> None:
        nonlocal best_nodes, best_value, previous_calls, previous_hits
        validate_population(population, eligible_set, k, population_size)
        values = tuple(item.mean_rumor_count for item in fitness)
        winner = elite_indices(population, values, 1)[0]
        genotype = population[winner]
        if (values[winner], individual_key(genotype)) < (best_value, individual_key(best_nodes)):
            best_nodes, best_value = genotype, values[winner]
        calls, hits = len(evaluations), cache_hits
        history.append(GAGeneration(
            generation, genotype, values[winner], best_value, fmean(values), max(values),
            len(set(population)), population, values, 0 if generation == 0 else elitism_count,
            calls - previous_calls, calls, hits - previous_hits, hits, perf_counter() - started,
        ))
        previous_calls, previous_hits = calls, hits

    record(0)
    for generation in range(1, max_generations + 1):
        values = tuple(item.mean_rumor_count for item in fitness)
        elite_slots = elite_indices(population, values, elitism_count)
        next_population = [population[i] for i in elite_slots]
        next_fitness = [fitness[i] for i in elite_slots]
        while len(next_population) < population_size:
            a = tournament_selection(population, values, tournament_size, rng=rng)
            b = tournament_selection(population, values, tournament_size, rng=rng)
            child = population[a]
            if rng.random() < crossover_rate:
                child = set_crossover(population[a], population[b], eligible, k, rng=rng)
            validate_individual(child, eligible_set, k)
            if rng.random() < mutation_rate:
                child = mutate_individual(child, eligible, k, rng=rng)
            validate_individual(child, eligible_set, k)
            child = repair_individual(child, eligible, k, rng=rng)
            validate_individual(child, eligible_set, k)
            next_population.append(child)
            next_fitness.append(score(child, generation))
        population, fitness = tuple(next_population), tuple(next_fitness)
        record(generation)

    upper = population_size + max_generations * (population_size - elitism_count)
    return GeneticAlgorithmResult(
        best_nodes, best_value, max_generations, tuple(history), tuple(evaluations),
        len(evaluations), len(evaluations) * number_of_simulations, requests, cache_hits,
        max_generations * elitism_count, upper, min(upper, comb(len(eligible), k)),
        rumor, eligible_set, parameters, seeds,
        fsum(item.runtime_seconds for item in evaluations), perf_counter() - started,
    )
