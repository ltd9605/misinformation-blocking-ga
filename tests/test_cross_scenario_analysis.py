"""Dataset-specific inference and conservative configuration decisions."""

import unittest

from experiments.analyze_cross_scenario_confirmation import aggregate_dataset, audit_main_reservations, audit_one_scenario, configuration_decision
from src.experiments.calibration import observation_summary


class ConfirmationAnalysisTests(unittest.TestCase):
    def fixture_rows(self):
        rows = []
        for dataset, scale in (("small", 1), ("large", 100)):
            for pop in (10, 20, 40):
                for repeat in range(3):
                    rows.append({"dataset": dataset, "population_size": pop, "status": "completed", "scenario_id": dataset+"_R",
                                 "rumor_seeds": [10], "profile_id": f"N{pop}", "independent_mean": scale*(repeat+1),
                                 "independent_MC_SE": .1, "training_fitness": 1, "independent_minus_training": scale*(repeat+1)-1,
                                 "selection_runtime_seconds": 2, "final_evaluation_runtime_seconds": 3,
                                 "optimization_evaluator_calls": 5, "CIC_simulations": 1000, "cache_hits": 4,
                                 "protector_seeds": [20+repeat]})
        return rows

    def test_means_are_grouped_by_dataset_not_pooled(self):
        groups = aggregate_dataset(self.fixture_rows())
        self.assertEqual(len(groups), 6)
        for group in groups:
            self.assertEqual(group["mean_over_GA_runs"], 2 if group["dataset"] == "small" else 200)
            self.assertEqual(group["independent_GA_runs"], 3)

    def test_between_run_variation_and_conditional_MC_error_remain_distinct(self):
        group = aggregate_dataset(self.fixture_rows())[0]
        self.assertNotEqual(group["std_across_GA_run_means"], group["mean_conditional_MC_SE"])
        self.assertGreater(group["CI95_over_GA_run_means_high"], group["mean_over_GA_runs"])

    def test_failed_rows_are_not_filled_with_zero_observations(self):
        rows = self.fixture_rows()
        rows[0] = {**rows[0], "status": "failed", "independent_mean": None}
        groups = aggregate_dataset(rows)
        group = next(g for g in groups if g["dataset"] == "small" and g["population_size"] == 10)
        self.assertEqual(group["independent_GA_runs"], 2)
        self.assertEqual(group["mean_over_GA_runs"], 2.5)

    def test_unresolved_CIs_retain_reference_without_claiming_equivalence(self):
        decision = configuration_decision({"completed_GA_runs": 27}, [{"conclusion": "insufficient_evidence_of_difference"}]*6)
        self.assertEqual(decision["decision"], "retain_reference_as_practical_candidate")
        self.assertFalse(decision["configurations_proven_equivalent"])
        self.assertFalse(decision["globally_optimal_GA_configuration_identified"])
        self.assertFalse(decision["main_experiments_authorized"])

    def test_resolved_effect_requires_review_without_automatic_GA_change(self):
        decision = configuration_decision({"completed_GA_runs": 27}, [{"conclusion": "lower_final_rumor_on_this_scenario_only_approximate_family_CI"}])
        self.assertEqual(decision["decision"], "review_reference_before_main_lock")
        self.assertFalse(decision["automatic_change_to_reference"])

    def test_alternative_worse_does_not_trigger_switch_away_from_reference(self):
        decision = configuration_decision({"completed_GA_runs": 27}, [{"conclusion": "higher_final_rumor_on_this_scenario_only_approximate_family_CI"}])
        self.assertEqual(decision["decision"], "retain_reference_as_practical_candidate")
        self.assertEqual(decision["contrasts_favoring_alternatives_requiring_review"], 0)

    def test_incomplete_confirmation_does_not_support_locking(self):
        decision = configuration_decision({"completed_GA_runs": 9}, [])
        self.assertEqual(decision["decision"], "insufficient_completed_runs")

    def test_main_holdout_rejects_prior_rumor_including_early_email_smoke(self):
        plan = {"protocol": {"datasets": ["email-Eu-core", "ego-Facebook", "Wiki-Vote"]},
                "old_scenarios": [], "matrix": [],
                "main_reservations": [{"dataset": "email-Eu-core", "rumor_seeds": [0]}]}
        with self.assertRaises(ValueError):
            audit_main_reservations(plan)

    def test_control_audit_uses_its_own_scenario_reference_seeds(self):
        scenario = {"scenario_id": "second", "reachable_count": 5, "reachable_fraction_of_graph": .5}
        matrix = [{"run_id": "first_r0", "scenario_id": "first", "profile_id": "reference", "repetition_index": 0, "S_eval": 2, "final_batch_seeds": [100]},
                  {"run_id": "second_r0", "scenario_id": "second", "profile_id": "reference", "repetition_index": 0, "S_eval": 2, "final_batch_seeds": [200]}]
        controls = {(0, 0): {"base_seed": 200, "rumor_counts": [1, 2], "final": observation_summary([1, 2], 10)}}
        audit = audit_one_scenario({"matrix": matrix}, scenario, {}, controls)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["raw_final_and_control_observations_recomputed"], 2)


if __name__ == "__main__":
    unittest.main()
