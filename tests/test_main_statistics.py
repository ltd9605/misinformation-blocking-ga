"""Primary paired effects and ratio confidence sets, including negative reductions."""

import json
import unittest

from experiments.main_statistics import average_reduction_sets, fieller_reduction, paired_effect, reduction_point, run_summary


class MainStatisticsTests(unittest.TestCase):
    def test_negative_reduction_is_not_clipped(self):
        self.assertEqual(reduction_point([3]*4, [2]*4), -.5)
        f = fieller_reduction([3]*4, [2]*4)
        self.assertEqual(f["point_estimate"], -.5)
        self.assertEqual(f["intervals"], [[-.5, -.5]])

    def test_ratio_of_means_differs_from_mean_of_ratios(self):
        self.assertAlmostEqual(reduction_point([1, 1, 2, 2], [1, 3, 4, 8]), 1-6/16)

    def test_undefined_control_mean_stays_null(self):
        self.assertIsNone(reduction_point([1]*4, [0]*4))

    def test_primary_family_interval_is_wider_than_pointwise(self):
        effect = paired_effect([1, 2, 3, 4], [2, 4, 2, 5], [.1]*4)
        self.assertEqual(effect["family_size"], 45)
        self.assertLess(effect["family_CI95_low"], effect["pointwise_CI95_low"])
        self.assertGreater(effect["family_CI95_high"], effect["pointwise_CI95_high"])
        self.assertEqual(effect["paired_run_count"], 4)

    def test_zero_difference_is_not_equivalence(self):
        effect = paired_effect([2, 3, 4, 5], [2, 3, 4, 5], [0]*4)
        self.assertFalse(effect["family_CI_excludes_zero"])
        self.assertFalse(effect["equivalence_established"])
        self.assertTrue(effect["conclusion"].startswith("insufficient_evidence"))

    def test_significant_direction_stays_limited_to_fixed_scope(self):
        a = paired_effect([1, 1, 1, 1], [100, 101, 99, 100], [.1]*4)
        b = paired_effect([100, 101, 99, 100], [1]*4, [.1]*4)
        self.assertEqual(a["conclusion"], "GA_lower_rumor_on_this_fixed_scope")
        self.assertEqual(b["conclusion"], "comparator_lower_rumor_on_this_fixed_scope")

    def test_MC_variance_and_run_variance_remain_separate(self):
        summary = run_summary([2, 3, 4, 5], [2]*4)
        self.assertEqual(summary["independent_run_count"], 4)
        self.assertEqual(summary["mean_conditional_MC_variance"], 4)
        self.assertLess(summary["algorithm_variance_component_raw"], 0)
        self.assertEqual(summary["algorithm_variance_component_nonnegative_display"], 0)

    def test_deterministic_methods_have_structural_zero_selection_variance(self):
        summary = run_summary([2, 4, 6, 8], [.1]*4, deterministic=True)
        self.assertTrue(summary["selection_variability_structurally_zero"])
        self.assertEqual(summary["structural_algorithm_variance"], 0)
        self.assertEqual(summary["algorithm_variance_component_nonnegative_display"], 0)
        self.assertGreater(summary["observed_variance_run_means"], 0)

    def test_Fieller_preserves_pairing_covariance(self):
        f = fieller_reduction([2, 4, 6, 8], [1, 2, 3, 4])
        self.assertAlmostEqual(f["point_estimate"], -1)
        self.assertAlmostEqual(f["intervals"][0][0], -1, places=6)
        self.assertAlmostEqual(f["intervals"][0][1], -1, places=6)

    def test_Fieller_disjoint_unbounded_interval_is_not_forced_finite(self):
        f = fieller_reduction([2]*4, [1, 1, 1, 100])
        self.assertEqual(f["kind"], "disjoint_unbounded")
        self.assertIsNone(f["intervals"][0][0])
        self.assertIsNone(f["intervals"][-1][1])
        json.dumps(f, allow_nan=False)

    def test_Fieller_all_real_set_remains_explicit(self):
        f = fieller_reduction([0]*4, [0]*4)
        self.assertEqual(f["kind"], "all_real_numbers")
        self.assertEqual(f["intervals"], [[None, None]])
        self.assertIsNone(f["point_estimate"])

    def test_dataset_average_keeps_equal_weights_and_negative_values(self):
        a = {"intervals": [[-.5, -.5]]}
        b = {"intervals": [[.2, .2]]}
        f = average_reduction_sets(a, b)
        self.assertEqual(f["weights"], [.5, .5])
        self.assertAlmostEqual(f["intervals"][0][0], -.15)
        self.assertAlmostEqual(f["intervals"][0][1], -.15)

    def test_unmatched_pairs_are_rejected(self):
        with self.assertRaises(ValueError):
            paired_effect([1, 2], [1], [0])
        with self.assertRaises(ValueError):
            fieller_reduction([1], [1])


if __name__ == "__main__":
    unittest.main()
