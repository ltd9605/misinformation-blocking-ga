"""Fixed-scenario aggregation, family45 contrasts and integrity of stored counts."""

from copy import deepcopy
import unittest

from experiments.analyze_main_experiments import METHODS, audit_records, dataset_summaries, method_comparisons, scenario_summaries
from src.experiments.calibration import observation_summary


class MainAnalysisTests(unittest.TestCase):
    def fixtures(self):
        scenarios = [{"dataset": "toy", "scenario_id": s, "rumor_seeds": [seed]} for s, seed in (("A", 10), ("B", 100))]
        plan = {"scenarios": scenarios, "base_protocol": {"datasets": ["toy"]},
                "request": {"analysis_policy": {"comparators": list(METHODS[:-1])}}}
        rows, counts = [], {}
        offsets = {"no_intervention": 10, "random": 12, "degree": 8, "pagerank": 7, "candidate_restricted_greedy": 6, "genetic_algorithm": 5}
        for s, scale in (("A", 1), ("B", 10)):
            for method in METHODS:
                for rep in range(4):
                    unit = f"{s}_{method}_{rep}"
                    value = scale*(offsets[method]+rep)
                    rows.append({"unit_id": unit, "dataset": "toy", "scenario_id": s, "algorithm": method, "repetition_index": rep,
                                 "rumor_mean": value, "rumor_MC_SE": .1, "status": "completed", "no_growth_fraction": 0,
                                 "selection_runtime_seconds": 1, "final_evaluation_runtime_seconds": 2, "total_runtime_seconds": 3,
                                 "total_evaluator_calls": 2, "CIC_simulations": 20, "cache_hits": 5,
                                 "training_fitness_diagnostic": value/2, "independent_minus_training": value/2,
                                 "protector_seeds": [] if method == "no_intervention" else [20+rep]})
                    counts[unit] = [value]*10
        return plan, rows, counts

    def test_scenario_summary_uses_four_runs_not_raw_MC_sample_count(self):
        plan, rows, _ = self.fixtures()
        summary = scenario_summaries(plan, rows)
        self.assertEqual(len(summary), 12)
        self.assertTrue(all(r["independent_run_count"] == 4 for r in summary))

    def test_negative_reduction_survives_scenario_and_dataset_aggregation(self):
        plan, rows, _ = self.fixtures()
        scenario = scenario_summaries(plan, rows)
        self.assertTrue(all(r["spread_reduction_fraction"] < 0 for r in scenario if r["algorithm"] == "random"))
        dataset = dataset_summaries(plan, rows, scenario)
        self.assertLess(next(r for r in dataset if r["algorithm"] == "random")["spread_reduction_fraction"], 0)

    def test_dataset_equal_weight_bundles_are_four_replications_not_eight_scenarios(self):
        plan, rows, _ = self.fixtures()
        scenario = scenario_summaries(plan, rows)
        dataset = dataset_summaries(plan, rows, scenario)
        ga = next(r for r in dataset if r["algorithm"] == "genetic_algorithm")
        self.assertEqual(ga["independent_run_count"], 4)
        self.assertEqual(ga["scenario_weights"], [.5, .5])
        self.assertAlmostEqual(ga["mean_rumor"], (6.5+65)/2)
        self.assertFalse(ga["scenario_population_inference"])
        self.assertEqual(ga["scenario_mean_min"], 6.5)
        self.assertEqual(ga["scenario_mean_max"], 65)

    def test_registered_comparisons_never_cross_scenarios_or_datasets(self):
        plan, rows, counts = self.fixtures()
        effects = method_comparisons(plan, rows, counts)
        self.assertEqual(len(effects), 15)  # two scenarios*five +one dataset*five
        self.assertEqual(sum(e["scope"] == "scenario" for e in effects), 10)
        self.assertTrue(all(e["paired_run_count"] == 4 and e["family_size"] == 45 for e in effects))
        effect = next(e for e in effects if e["scope"] == "scenario" and e["scenario_id"] == "A" and e["comparator"] == "no_intervention")
        self.assertEqual(effect["mean_difference"], -5)

    def test_missing_run_is_not_silently_dropped_for_primary_inference(self):
        plan, rows, counts = self.fixtures()
        rows = [r for r in rows if not (r["scenario_id"] == "A" and r["algorithm"] == "genetic_algorithm" and r["repetition_index"] == 3)]
        summary = scenario_summaries(plan, rows)
        group = next(r for r in summary if r["scenario_id"] == "A" and r["algorithm"] == "genetic_algorithm")
        self.assertEqual(group["status"], "incomplete_no_primary_inference")
        effects = method_comparisons(plan, rows, counts)
        self.assertFalse(any(e["scenario_id"] == "A" for e in effects))

    def audit_fixture(self):
        row = {"unit_id": "u", "dataset": "toy", "scenario_id": "s", "algorithm": "no_intervention", "rumor_seeds": [10],
               "k": 1, "S_opt": 3, "S_eval_per_batch": 2, "final_batch_seeds": [100, 102], "budgeted_optimization_CIC_upper": 0}
        select = {"row": row, "graph_nodes": 3, "graph_edges": 2, "protector_seeds": [], "timing": {"optimization_evaluation_count": 0},
                  "selection_details": {}, "evaluator_calls": 0, "CIC_simulations": 0}
        final = {"row": row, "protector_seeds": [], "selection_sha256": "sealed", "base_random_seed": 100,
                 "evaluator_calls": 1, "CIC_simulations": 2, "graph_nodes": 3, "graph_edges": 2,
                 "raw_counts": {"rumor_count": [1, 2], "protector_count": [0, 0], "inactive_count": [2, 1], "steps": [0, 1]},
                 "statistics": observation_summary([1, 2], 3), "mean_protector_count": 0, "mean_inactive_count": 1.5}
        plan = {"graphs": [{"dataset": "toy", "nodes": 3, "edges": 2}], "scenarios": [{"scenario_id": "s"}]}
        state = {"result_sha256": {"select_u": "sealed"}}
        return plan, state, {"u": select}, {("u", 0): final}

    def test_raw_count_audit_recomputes_observations(self):
        audit = audit_records(*self.audit_fixture())
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["raw_final_CIC_observations_recomputed"], 2)
        self.assertEqual(audit["official_resimulations_for_audit"], 0)

    def test_corrupt_raw_counts_or_wrong_seed_are_rejected(self):
        plan, state, selections, batches = self.audit_fixture()
        changed = deepcopy(batches)
        changed[("u", 0)]["raw_counts"]["inactive_count"][0] = 3
        with self.assertRaises(ValueError):
            audit_records(plan, state, selections, changed)
        changed = deepcopy(batches)
        changed[("u", 0)]["base_random_seed"] = 101
        with self.assertRaises(ValueError):
            audit_records(plan, state, selections, changed)


if __name__ == "__main__":
    unittest.main()
