"""Metrics over independent final observations; no optimization-score mixing."""

from math import sqrt
from typing import Any

from src.evaluation import MonteCarloResult


def final_metrics(estimate: MonteCarloResult, control: MonteCarloResult) -> dict[str, Any]:
    """Keep ddof=0 std and add sample-corrected SE; undefined ratios stay null."""
    s = estimate.number_of_simulations
    sample_std = estimate.std_rumor_count * sqrt(s / (s - 1)) if s > 1 else None
    se = estimate.std_rumor_count / sqrt(s - 1) if s > 1 else None
    reduction = ((control.mean_rumor_count - estimate.mean_rumor_count) / control.mean_rumor_count
                 if control.mean_rumor_count > 0 else None)
    return {
        "rumor_mean": estimate.mean_rumor_count, "rumor_std_population": estimate.std_rumor_count,
        "rumor_std_sample": sample_std, "rumor_standard_error": se,
        "protector_mean": estimate.mean_protector_count, "inactive_mean": estimate.mean_inactive_count,
        "min_rumor_count": estimate.min_rumor_count, "max_rumor_count": estimate.max_rumor_count,
        "control_rumor_mean": control.mean_rumor_count,
        "absolute_rumor_reduction": control.mean_rumor_count - estimate.mean_rumor_count,
        "rumor_reduction_fraction": reduction,
        "rumor_reduction_percent": 100 * reduction if reduction is not None else None,
    }
