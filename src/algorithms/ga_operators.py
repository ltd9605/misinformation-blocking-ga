"""Set-based GA operators with explicit invariant checks and private RNG input."""

from collections.abc import Hashable, Iterable, Sequence
from math import isfinite
from random import Random

from src.diffusion.cic import _node_sort_key


Individual = frozenset[Hashable]


def _integer(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def individual_key(individual: Individual) -> tuple:
    """Canonical genotype tie-break independent of hashes/insertion order."""
    return tuple(sorted((_node_sort_key(node) for node in individual)))


def _eligible(eligible_nodes: Iterable[Hashable], k: int) -> list[Hashable]:
    _integer("k", k, 0)
    nodes = sorted(set(eligible_nodes), key=_node_sort_key)
    if k > len(nodes):
        raise ValueError("k exceeds eligible node count")
    return nodes


def validate_individual(individual: Iterable[Hashable], eligible_nodes: Iterable[Hashable], k: int) -> Individual:
    """Reject wrong cardinality, repeated nodes and any node outside V minus R."""
    _integer("k", k, 0)
    values = tuple(individual)
    genes = frozenset(values)
    if len(values) != k or len(genes) != k:
        raise ValueError("An individual must contain exactly k distinct nodes")
    if genes.difference(eligible_nodes):
        raise ValueError("Individual contains nodes outside the eligible set")
    return genes


def validate_population(population: Sequence[Individual], eligible_nodes: Iterable[Hashable],
                        k: int, population_size: int) -> None:
    """Check population size and every individual, allowing duplicate genotypes."""
    _integer("population_size", population_size, 1)
    if len(population) != population_size:
        raise ValueError("Population size changed")
    eligible = frozenset(eligible_nodes)
    for individual in population:
        validate_individual(individual, eligible, k)


def initialize_population(eligible_nodes: Iterable[Hashable], k: int, population_size: int,
                          *, rng: Random) -> tuple[Individual, ...]:
    """Sample each k-set uniformly; genotype duplicates across slots are allowed."""
    nodes = _eligible(eligible_nodes, k)
    _integer("population_size", population_size, 1)
    population = tuple(frozenset(rng.sample(nodes, k)) for _ in range(population_size))
    validate_population(population, nodes, k, population_size)
    return population


def repair_individual(individual: Iterable[Hashable], eligible_nodes: Iterable[Hashable], k: int,
                      *, rng: Random) -> Individual:
    """Drop invalid/duplicate genes; uniformly trim or fill to cardinality k."""
    nodes = _eligible(eligible_nodes, k)
    allowed = frozenset(nodes)
    kept = set(individual) & allowed
    if len(kept) > k:
        kept = set(rng.sample(sorted(kept, key=_node_sort_key), k))
    if len(kept) < k:
        available = [node for node in nodes if node not in kept]
        kept.update(rng.sample(available, k - len(kept)))
    return validate_individual(frozenset(kept), allowed, k)


def set_crossover(parent_a: Individual, parent_b: Individual,
                  eligible_nodes: Iterable[Hashable], k: int, *, rng: Random) -> Individual:
    """Keep parental intersection and sample the remaining genes from the union."""
    nodes = _eligible(eligible_nodes, k)
    a = validate_individual(parent_a, nodes, k)
    b = validate_individual(parent_b, nodes, k)
    common = a & b
    alternatives = sorted(a ^ b, key=_node_sort_key)
    child = common | frozenset(rng.sample(alternatives, k - len(common)))
    return validate_individual(child, nodes, k)


def mutate_individual(individual: Individual, eligible_nodes: Iterable[Hashable], k: int,
                      *, rng: Random) -> Individual:
    """Replace exactly one gene when k>0 and an outside candidate exists."""
    nodes = _eligible(eligible_nodes, k)
    genes = validate_individual(individual, nodes, k)
    outside = [node for node in nodes if node not in genes]
    if k == 0 or not outside:
        return genes
    removed = rng.choice(sorted(genes, key=_node_sort_key))
    added = rng.choice(outside)
    return validate_individual((genes - {removed}) | {added}, nodes, k)


def _rank(population: Sequence[Individual], fitness_values: Sequence[float]) -> list[int]:
    if not population or len(population) != len(fitness_values):
        raise ValueError("Population and fitness values must be nonempty and aligned")
    if any(not isfinite(value) for value in fitness_values):
        raise ValueError("Fitness values must be finite")
    return sorted(range(len(population)), key=lambda i: (fitness_values[i], individual_key(population[i]), i))


def tournament_selection(population: Sequence[Individual], fitness_values: Sequence[float],
                         tournament_size: int, *, rng: Random) -> int:
    """Return a winning slot index; contestants are sampled without replacement."""
    _rank(population, fitness_values)
    _integer("tournament_size", tournament_size, 1)
    if tournament_size > len(population):
        raise ValueError("tournament_size exceeds population size")
    contestants = rng.sample(range(len(population)), tournament_size)
    return min(contestants, key=lambda i: (fitness_values[i], individual_key(population[i]), i))


def elite_indices(population: Sequence[Individual], fitness_values: Sequence[float],
                   elitism_count: int) -> tuple[int, ...]:
    """Return the best E slots in deterministic fitness/genotype/index order."""
    ranked = _rank(population, fitness_values)
    _integer("elitism_count", elitism_count, 0)
    if elitism_count > len(population):
        raise ValueError("elitism_count exceeds population size")
    return tuple(ranked[:elitism_count])
