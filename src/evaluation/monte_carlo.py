"""Reproducible Monte Carlo estimates from unchanged CIC simulations."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from statistics import fmean, pstdev
from time import perf_counter

import networkx as nx

from src.diffusion import TieBreakingRule, simulate_cic


@dataclass(frozen=True)
class SimulationResult:
    """Compact raw observation from one CIC run, indexed from zero.

    Store counts and propagation steps rather than retaining every node set
    and activation layer from every run. random_seed permits direct replay.
    """

    simulation_index: int
    random_seed: int
    rumor_count: int
    protector_count: int
    inactive_count: int
    steps: int


@dataclass(frozen=True)
class MonteCarloResult:
    """CIC summary with population rumor standard deviation (denominator S).

    All statistical fields and raw observations are reproducible. Wall-clock
    runtime is diagnostic and excluded from value equality. S=1 has std=0.
    """

    mean_rumor_count: float
    std_rumor_count: float
    mean_protector_count: float
    mean_inactive_count: float
    min_rumor_count: int
    max_rumor_count: int
    number_of_simulations: int
    base_random_seed: int
    tie_breaking: TieBreakingRule
    raw_results: tuple[SimulationResult, ...]
    runtime_seconds: float = field(compare=False)


def evaluate_cic(
    graph: nx.Graph,
    rumor_seeds: Iterable[Hashable],
    protector_seeds: Iterable[Hashable],
    propagation_probability: float,
    number_of_simulations: int,
    *,
    base_random_seed: int,
    tie_breaking: TieBreakingRule | str,
) -> MonteCarloResult:
    """Estimate rumor spread by calling simulate_cic exactly S times.

    S must be a positive integer and base_random_seed a nonnegative integer;
    booleans are rejected. Run i uses seed base_random_seed + i for i in
    range(S). This schedule is independent of graph/cascade configuration and
    does not use the global RNG. Nonnegative seeds avoid Random's equivalence
    between negative and positive integer seeds.

    Materialize seed iterables once, so generators describe the same R/P in
    every run. All graph/seed/probability/tie validation is delegated to the
    verified CIC implementation on the first run. IC/CIC semantics are not
    reimplemented here; their exceptions propagate unchanged.

    Return means, population rumor std (not standard error or sample std),
    min/max and compact raw records. Runtime covers seed materialization,
    all simulations and aggregation, excluding file I/O and dataset loading.

    Using the same base seed across protector configurations reuses the seed
    schedule. It does not guarantee identical edge-level random outcomes:
    CIC's number/order of valid attempts may depend on the configuration.
    """
    if isinstance(number_of_simulations, bool) or not isinstance(number_of_simulations, int):
        raise TypeError("number_of_simulations must be a positive integer")
    if number_of_simulations < 1:
        raise ValueError("number_of_simulations must be at least 1")
    if isinstance(base_random_seed, bool) or not isinstance(base_random_seed, int):
        raise TypeError("base_random_seed must be a nonnegative integer")
    if base_random_seed < 0:
        raise ValueError("base_random_seed must be nonnegative")

    started = perf_counter()
    rumor = frozenset(rumor_seeds)
    protector = frozenset(protector_seeds)
    observations = []
    for index in range(number_of_simulations):
        simulation_seed = base_random_seed + index
        result = simulate_cic(
            graph, rumor, protector, propagation_probability,
            tie_breaking=tie_breaking, random_seed=simulation_seed,
        )
        observations.append(SimulationResult(
            simulation_index=index,
            random_seed=simulation_seed,
            rumor_count=result.rumor_count,
            protector_count=result.protector_count,
            inactive_count=result.inactive_count,
            steps=result.steps,
        ))

    raw_results = tuple(observations)
    rumor_counts = tuple(run.rumor_count for run in raw_results)
    mean_rumor = fmean(rumor_counts)
    std_rumor = pstdev(rumor_counts)
    mean_protector = fmean(run.protector_count for run in raw_results)
    mean_inactive = fmean(run.inactive_count for run in raw_results)
    minimum = min(rumor_counts)
    maximum = max(rumor_counts)
    return MonteCarloResult(
        mean_rumor_count=mean_rumor,
        std_rumor_count=std_rumor,
        mean_protector_count=mean_protector,
        mean_inactive_count=mean_inactive,
        min_rumor_count=minimum,
        max_rumor_count=maximum,
        number_of_simulations=number_of_simulations,
        base_random_seed=base_random_seed,
        tie_breaking=TieBreakingRule(tie_breaking),
        raw_results=raw_results,
        runtime_seconds=perf_counter() - started,
    )
