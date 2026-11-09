"""Independent checks of summary formulas and undefined cases."""

from dataclasses import replace
from math import sqrt
import unittest

import networkx as nx

from src.evaluation import evaluate_cic
from src.experiments.metrics import final_metrics


class ExperimentMetricTests(unittest.TestCase):
    def setUp(self):
        self.estimate = evaluate_cic(nx.path_graph(4), [0], [3], 1, 4,
                                     base_random_seed=0, tie_breaking="protector-priority")

    def test_population_std_sample_std_and_standard_error(self):
        # Known observations [1, 2, 3, 4]: mean 2.5, population variance 1.25.
        estimate = replace(self.estimate, mean_rumor_count=2.5, std_rumor_count=sqrt(1.25))
        metrics = final_metrics(estimate, replace(self.estimate, mean_rumor_count=5))
        self.assertAlmostEqual(metrics["rumor_std_sample"], sqrt(5 / 3))
        self.assertAlmostEqual(metrics["rumor_standard_error"], sqrt(5 / 3) / 2)
        self.assertEqual(metrics["rumor_reduction_fraction"], 0.5)
        self.assertEqual(metrics["rumor_reduction_percent"], 50)

    def test_single_observation_has_undefined_sample_uncertainty(self):
        metrics = final_metrics(replace(self.estimate, number_of_simulations=1, std_rumor_count=0), self.estimate)
        self.assertIsNone(metrics["rumor_std_sample"])
        self.assertIsNone(metrics["rumor_standard_error"])

    def test_zero_control_has_no_relative_reduction(self):
        empty = replace(self.estimate, mean_rumor_count=0)
        metrics = final_metrics(empty, empty)
        self.assertEqual(metrics["absolute_rumor_reduction"], 0)
        self.assertIsNone(metrics["rumor_reduction_fraction"])
        self.assertIsNone(metrics["rumor_reduction_percent"])

    def test_negative_measured_reductions_are_preserved(self):
        metrics = final_metrics(replace(self.estimate, mean_rumor_count=3), replace(self.estimate, mean_rumor_count=2))
        self.assertEqual(metrics["absolute_rumor_reduction"], -1)
        self.assertEqual(metrics["rumor_reduction_percent"], -50)
