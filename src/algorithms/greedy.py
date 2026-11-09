"""Full and explicitly candidate-restricted Greedy using the CIC evaluator."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from math import fsum
from numbers import Real
from time import perf_counter

import networkx as nx

from src.diffusion import TieBreakingRule
from src.evaluation import evaluate_cic
from .baselines import _candidates


@dataclass(frozen=True)
class GreedyCost:
    """Exact work counts, not a wall-clock runtime prediction."""

    candidate_count: int
    protector_budget: int
    number_of_simulations: int
    evaluation_count: int
    cic_simulation_count: int


def estimate_greedy_cost(candidate_count: int, k: int, number_of_simulations: int) -> GreedyCost:
    """Return E=k*m-k*(k-1)/2 evaluator calls and E*S CIC simulations.

    Full Greedy has m=|V|-|R|. Restricted Greedy has m=|candidate pool|.
    There are no initial/final evaluation calls beyond the candidate trials.
    """
    for name, value in (("candidate_count", candidate_count), ("k", k),
                        ("number_of_simulations", number_of_simulations)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if candidate_count < 0 or k < 0 or k > candidate_count:
        raise ValueError("Require 0 <= k <= candidate_count")
    if number_of_simulations < 1:
        raise ValueError("number_of_simulations must be at least 1")
    evaluations = k * candidate_count - k * (k - 1) // 2
    return GreedyCost(candidate_count, k, number_of_simulations,
                      evaluations, evaluations * number_of_simulations)


@dataclass(frozen=True)
class GreedyCandidateEvaluation:
    """Compact trial summary; replay using the result's seed/model settings."""

    candidate_node: Hashable
    mean_rumor_count: float
    std_rumor_count: float
    mean_protector_count: float
    mean_inactive_count: float
    evaluation_runtime_seconds: float = field(compare=False)


@dataclass(frozen=True)
class GreedyStep:
    """One committed choice plus all candidate scores considered at that step."""

    step_index: int
    selected_node: Hashable
    protector_nodes: frozenset[Hashable]
    mean_rumor_count: float
    std_rumor_count: float
    candidate_evaluations: tuple[GreedyCandidateEvaluation, ...]

    @property
    def evaluation_count(self) -> int:
        """Count evaluator calls in this step."""
        return len(self.candidate_evaluations)


@dataclass(frozen=True)
class GreedyResult:
    """Auditable Greedy history; timing is excluded from reproducible equality.

    k=0 returns no steps/evaluations and final_mean_rumor_count=None. The empty
    protector set is not assigned a fabricated score. All stored sets are frozen.
    """

    algorithm: str
    protector_nodes: frozenset[Hashable]
    selection_order: tuple[Hashable, ...]
    candidate_nodes: frozenset[Hashable]
    base_random_seed: int
    tie_breaking: TieBreakingRule
    number_of_simulations: int
    steps: tuple[GreedyStep, ...]
    evaluation_count: int
    cic_simulation_count: int
    evaluation_runtime_seconds: float = field(compare=False)
    runtime_seconds: float = field(compare=False)

    @property
    def final_mean_rumor_count(self) -> float | None:
        """Return the final selected trial's optimization score, if evaluated."""
        return self.steps[-1].mean_rumor_count if self.steps else None


def _validate_settings(p: float, base_random_seed: int, tie_breaking: TieBreakingRule | str) -> TieBreakingRule:
    """Check the evaluator's model settings even when k=0 needs no evaluation."""
    if isinstance(p, bool) or not isinstance(p, Real):
        raise TypeError("propagation_probability must be a real number")
    if not 0 <= p <= 1:
        raise ValueError("propagation_probability must be finite and in [0, 1]")
    if isinstance(base_random_seed, bool) or not isinstance(base_random_seed, int):
        raise TypeError("base_random_seed must be a nonnegative integer")
    if base_random_seed < 0:
        raise ValueError("base_random_seed must be nonnegative")
    if not isinstance(tie_breaking, str):
        raise TypeError("tie_breaking must be a TieBreakingRule or string")
    return TieBreakingRule(tie_breaking)


def _select(
    graph: nx.Graph, rumor: frozenset[Hashable], candidates: list[Hashable],
    k: int, p: float, simulations: int, base_random_seed: int,
    tie_breaking: TieBreakingRule | str, algorithm: str, started: float,
) -> GreedyResult:
    cost = estimate_greedy_cost(len(candidates), k, simulations)
    rule = _validate_settings(p, base_random_seed, tie_breaking)
    selected: set[Hashable] = set()
    chosen = []
    history = []
    evaluations = 0
    for step_index in range(1, k + 1):
        trials = []
        best = None
        for candidate in candidates:
            if candidate in selected:
                continue
            estimate = evaluate_cic(
                graph, rumor, frozenset(selected | {candidate}), p, simulations,
                base_random_seed=base_random_seed, tie_breaking=rule,
            )
            evaluations += 1
            trial = GreedyCandidateEvaluation(
                candidate, estimate.mean_rumor_count, estimate.std_rumor_count,
                estimate.mean_protector_count, estimate.mean_inactive_count, estimate.runtime_seconds,
            )
            trials.append(trial)
            # Candidates are in canonical order; strict comparison preserves
            # the first (smallest label) on exactly equal mean rumor counts.
            if best is None or trial.mean_rumor_count < best.mean_rumor_count:
                best = trial
        if best is None:
            raise RuntimeError("Greedy ran out of candidates before filling the budget")
        selected.add(best.candidate_node)
        chosen.append(best.candidate_node)
        history.append(GreedyStep(
            step_index, best.candidate_node, frozenset(selected), best.mean_rumor_count,
            best.std_rumor_count, tuple(trials),
        ))
    if evaluations != cost.evaluation_count:
        raise RuntimeError("Greedy evaluation count differs from its exact work estimate")
    evaluation_time = fsum(trial.evaluation_runtime_seconds
                          for step in history for trial in step.candidate_evaluations)
    return GreedyResult(
        algorithm, frozenset(selected), tuple(chosen), frozenset(candidates),
        base_random_seed, rule, simulations, tuple(history), evaluations,
        evaluations * simulations, evaluation_time, perf_counter() - started,
    )


def select_greedy(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
    propagation_probability: float, number_of_simulations: int,
    *, base_random_seed: int, tie_breaking: TieBreakingRule | str,
) -> GreedyResult:
    """Full Greedy: exhaust every eligible remaining node at each of k steps.

    Start P empty. Evaluate P union {v} with evaluate_cic for every remaining
    v outside R/P; commit the minimum mean rumor count, ties by canonical label.
    Continue to exactly k even if noisy scores do not decrease. Full means full
    candidate coverage per step, not global optimization over all k-subsets.

    Every trial and step uses the same base seed (simulation i uses base+i).
    This is reproducible, but does not guarantee common edge-level random draws
    across P sets. Reported scores were used for selection and are not held-out
    estimates. The method never silently restricts or prefilters candidates.
    Input graph/seeds are not modified; node labels follow the CIC contract.
    Runtime includes validation, evaluation and selection, excluding load/I/O.
    """
    started = perf_counter()
    rumor = frozenset(rumor_seeds)
    _, candidates = _candidates(graph, rumor, k)
    return _select(graph, rumor, candidates, k, propagation_probability, number_of_simulations,
                   base_random_seed, tie_breaking, "full-greedy", started)


def select_candidate_restricted_greedy(
    graph: nx.Graph, rumor_seeds: Iterable[Hashable], k: int,
    propagation_probability: float, number_of_simulations: int,
    *, candidate_nodes: Iterable[Hashable], base_random_seed: int,
    tie_breaking: TieBreakingRule | str,
) -> GreedyResult:
    """Candidate-Restricted Greedy over an explicitly supplied fixed pool.

    This is not Full Greedy. Pool nodes must exist and exclude rumor seeds;
    duplicates within the pool are combined. At every step, exhaust all remaining
    nodes of this pool, with the same scoring/tie rules as select_greedy.
    No graph nodes/edges are removed to implement the restriction.
    """
    started = perf_counter()
    rumor = frozenset(rumor_seeds)
    _, eligible = _candidates(graph, rumor, 0)
    pool = frozenset(candidate_nodes)
    if pool.difference(graph):
        raise ValueError("Candidate nodes must exist in graph")
    if pool & rumor:
        raise ValueError("Candidate pool must exclude rumor seeds")
    candidates = [node for node in eligible if node in pool]
    return _select(graph, rumor, candidates, k, propagation_probability, number_of_simulations,
                   base_random_seed, tie_breaking, "candidate-restricted-greedy", started)
