"""Independent tests of set-based genetic operators and invariants."""

from random import Random
import unittest

from src.algorithms.ga_operators import (
    elite_indices, initialize_population, mutate_individual, repair_individual,
    set_crossover, tournament_selection, validate_individual, validate_population,
)


class GAOperatorTests(unittest.TestCase):
    def test_initialization_produces_exact_size_and_valid_sparse_sets(self) -> None:
        eligible = [3, 17, 9000, 60000]
        population = initialize_population(eligible, 2, 12, rng=Random(42))
        self.assertEqual(len(population), 12)
        for individual in population:
            self.assertIsInstance(individual, frozenset)
            self.assertEqual(len(individual), 2)
            self.assertTrue(individual <= set(eligible))

    def test_initialization_is_reproducible_independent_of_candidate_order(self) -> None:
        self.assertEqual(initialize_population([90, 3, 17], 2, 5, rng=Random(7)),
                         initialize_population([17, 3, 90], 2, 5, rng=Random(7)))

    def test_zero_and_full_budgets_allow_duplicate_population_slots(self) -> None:
        self.assertEqual(initialize_population([3, 17], 0, 5, rng=Random(7)), (frozenset(),) * 5)
        self.assertEqual(initialize_population([3, 17], 2, 5, rng=Random(7)), (frozenset({3, 17}),) * 5)

    def test_initialization_rejects_invalid_size_and_budget(self) -> None:
        for k, size in ((3, 5), (-1, 5), (1, 0), (True, 3), (1, True)):
            with self.assertRaises((ValueError, TypeError)):
                initialize_population([3, 17], k, size, rng=Random(7))

    def test_repair_drops_duplicates_and_ineligible_genes_then_fills(self) -> None:
        result = repair_individual([0, 3, 3, 99], [3, 17, 90], 2, rng=Random(42))
        self.assertEqual(len(result), 2)
        self.assertIn(3, result)
        self.assertTrue(result <= {3, 17, 90})

    def test_repair_trims_surplus_and_handles_empty_budget(self) -> None:
        self.assertEqual(len(repair_individual([3, 17, 90], [3, 17, 90], 2, rng=Random(42))), 2)
        self.assertEqual(repair_individual([3, 99], [3, 17], 0, rng=Random(42)), frozenset())

    def test_repair_replays_and_does_not_modify_input(self) -> None:
        genes = [3, 3, 99]
        first = repair_individual(genes, [3, 17, 90], 2, rng=Random(42))
        self.assertEqual(first, repair_individual(reversed(genes), [90, 17, 3], 2, rng=Random(42)))
        self.assertEqual(genes, [3, 3, 99])

    def test_repair_rejects_impossible_budget(self) -> None:
        with self.assertRaises(ValueError):
            repair_individual([], [3], 2, rng=Random(42))

    def test_crossover_preserves_intersection_and_uses_parental_union(self) -> None:
        a, b = frozenset({3, 17, 90}), frozenset({17, 90, 60000})
        for seed in range(10):
            child = set_crossover(a, b, [3, 17, 90, 60000, 80000], 3, rng=Random(seed))
            self.assertEqual(len(child), 3)
            self.assertTrue(a & b <= child)
            self.assertTrue(child <= a | b)
        self.assertEqual(a, {3, 17, 90})
        self.assertEqual(b, {17, 90, 60000})

    def test_crossover_handles_identical_and_empty_parents(self) -> None:
        a = frozenset({3, 17})
        self.assertEqual(set_crossover(a, a, [3, 17, 90], 2, rng=Random(7)), a)
        self.assertEqual(set_crossover(frozenset(), frozenset(), [], 0, rng=Random(7)), frozenset())

    def test_crossover_rejects_invalid_parents(self) -> None:
        with self.assertRaises(ValueError):
            set_crossover(frozenset({3}), frozenset({17, 90}), [3, 17, 90], 2, rng=Random(7))

    def test_mutation_replaces_exactly_one_node(self) -> None:
        parent = frozenset({3, 17})
        for seed in range(10):
            child = mutate_individual(parent, [3, 17, 90, 60000], 2, rng=Random(seed))
            self.assertEqual(len(child), 2)
            self.assertEqual(len(parent - child), 1)
            self.assertEqual(len(child - parent), 1)
            self.assertTrue(child <= {3, 17, 90, 60000})
        self.assertEqual(parent, {3, 17})

    def test_mutation_noop_when_zero_budget_or_no_replacement_exists(self) -> None:
        self.assertEqual(mutate_individual(frozenset(), [3], 0, rng=Random(7)), frozenset())
        self.assertEqual(mutate_individual(frozenset({3}), [3], 1, rng=Random(7)), {3})

    def test_tournament_selects_minimum_when_all_slots_compete(self) -> None:
        population = (frozenset({3}), frozenset({17}), frozenset({90}))
        self.assertEqual(tournament_selection(population, [5, 1, 3], 3, rng=Random(42)), 1)

    def test_tournament_uses_genotype_then_slot_on_equal_fitness(self) -> None:
        population = (frozenset({90}), frozenset({3}), frozenset({3}))
        for seed in range(5):
            self.assertEqual(tournament_selection(population, [1, 1, 1], 3, rng=Random(seed)), 1)

    def test_tournament_sampling_replays_and_rejects_bad_size(self) -> None:
        population = (frozenset({3}), frozenset({17}), frozenset({90}))
        self.assertEqual(tournament_selection(population, [1, 2, 3], 2, rng=Random(7)),
                         tournament_selection(population, [1, 2, 3], 2, rng=Random(7)))
        for size in (0, 4, True):
            with self.assertRaises((TypeError, ValueError)):
                tournament_selection(population, [1, 2, 3], size, rng=Random(7))

    def test_elites_use_fitness_and_canonical_tie_break(self) -> None:
        population = (frozenset({90}), frozenset({17}), frozenset({3}))
        self.assertEqual(elite_indices(population, [2, 1, 1], 2), (2, 1))
        self.assertEqual(elite_indices(population, [2, 1, 1], 0), ())
        with self.assertRaises(ValueError):
            elite_indices(population, [2, 1, 1], 4)

    def test_population_validation_rejects_size_or_genotype_errors(self) -> None:
        with self.assertRaises(ValueError):
            validate_population((frozenset({3}),), [3, 17], 1, 2)
        with self.assertRaises(ValueError):
            validate_population((frozenset({99}),), [3, 17], 1, 1)
        with self.assertRaises(ValueError):
            validate_individual([3, 3], [3, 17], 2)

    def test_ranking_rejects_misaligned_or_nonfinite_fitness(self) -> None:
        for fitness in ([], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError):
                elite_indices((frozenset({3}),), fitness, 1)

    def test_supported_mixed_labels_replay(self) -> None:
        candidates = [3, "a", ("tuple", 1), frozenset({"x", "y"})]
        self.assertEqual(initialize_population(candidates, 2, 5, rng=Random(42)),
                         initialize_population(reversed(candidates), 2, 5, rng=Random(42)))
