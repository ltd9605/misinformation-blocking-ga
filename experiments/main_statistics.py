"""Prespecified main statistics: paired t intervals and descriptive Fieller sets.

No propagation or optimization is performed. Independent algorithm runs, not
individual CIC observations, are the units for the family45 primary effects.
"""

from math import copysign, isfinite, sqrt
from statistics import covariance, mean, stdev, variance

from scipy.stats import t


def run_summary(values: list[float], conditional_ses: list[float], *, deterministic: bool = False) -> dict:
    """Keep conditional MC noise separate from dispersion of independent run means."""
    if len(values) != len(conditional_ses) or not values:
        raise ValueError("Matching nonempty run means/conditional errors required")
    n = len(values)
    sd = stdev(values) if n > 1 else None
    se = sd/sqrt(n) if sd is not None else None
    half = float(t.ppf(.975, n-1))*se if se is not None else None
    observed = sd*sd if sd is not None else None
    mc = mean(s*s for s in conditional_ses)
    raw = observed-mc if observed is not None else None
    return {"independent_run_count": n, "mean_rumor": mean(values), "SD_between_run_means_including_MC": sd,
            "SE_across_run_means": se, "CI95_run_means_low": mean(values)-half if half is not None else None,
            "CI95_run_means_high": mean(values)+half if half is not None else None,
            "mean_conditional_MC_SE": mean(conditional_ses), "mean_conditional_MC_variance": mc,
            "observed_variance_run_means": observed, "algorithm_variance_component_raw": raw,
            "algorithm_variance_component_nonnegative_display": 0 if deterministic else max(0, raw) if raw is not None else None,
            "selection_variability_structurally_zero": deterministic,
            "structural_algorithm_variance": 0 if deterministic else None,
            "variance_decomposition_is_descriptive": True}


def paired_effect(first: list[float], second: list[float], conditional_ses: list[float], family_size: int = 45) -> dict:
    """GA-minus-comparator effect; family CI is the primary inference rule."""
    if len(first) != len(second) or len(first) != len(conditional_ses) or len(first) < 2:
        raise ValueError("At least two aligned run pairs required")
    differences = [a-b for a, b in zip(first, second)]
    n, delta = len(differences), mean(differences)
    sd = stdev(differences)
    se = sd/sqrt(n)
    point = float(t.ppf(.975, n-1))*se
    family = float(t.ppf(1-.05/(2*family_size), n-1))*se
    low, high = delta-family, delta+family
    conclusion = "insufficient_evidence_of_difference_not_equivalence"
    if sd > 0 and high < 0:
        conclusion = "GA_lower_rumor_on_this_fixed_scope"
    elif sd > 0 and low > 0:
        conclusion = "comparator_lower_rumor_on_this_fixed_scope"
    return {"difference_direction": "GA_minus_comparator_negative_favors_GA", "paired_run_count": n,
            "mean_difference": delta, "SD_paired_run_differences": sd, "SE_paired_run_differences": se,
            "pointwise_CI95_low": delta-point, "pointwise_CI95_high": delta+point,
            "family_size": family_size, "family_CI95_low": low, "family_CI95_high": high,
            "family_CI_excludes_zero": sd > 0 and (high < 0 or low > 0), "conclusion": conclusion,
            "zero_observed_variance_warning": sd == 0,
            "mean_conditional_MC_SE_of_difference": mean(conditional_ses),
            "conditional_MC_variance_of_difference_mean": mean(s*s for s in conditional_ses),
            "algorithm_difference_variance_component_raw": sd*sd-mean(s*s for s in conditional_ses),
            "equivalence_established": False}


def reduction_point(method_means: list[float], control_means: list[float]) -> float | None:
    """Ratio of means, preserving negative reductions rather than clipping."""
    denominator = mean(control_means)
    return 1-mean(method_means)/denominator if denominator > 0 else None


def _merge_intervals(intervals: list[list[float | None]]) -> list[list[float | None]]:
    """None at lower/upper endpoint represents negative/positive infinity."""
    ordered = sorted(intervals, key=lambda pair: float("-inf") if pair[0] is None else pair[0])
    merged = []
    for lo, hi in ordered:
        if not merged or (merged[-1][1] is not None and lo is not None and lo > merged[-1][1]):
            merged.append([lo, hi])
        elif merged[-1][1] is None or hi is None:
            merged[-1][1] = None
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return merged


def _interval_kind(intervals: list[list[float | None]]) -> str:
    if not intervals:
        return "empty_confidence_set"
    if len(intervals) > 1:
        return "disjoint_unbounded" if any(None in x for x in intervals) else "disjoint_bounded"
    lo, hi = intervals[0]
    if lo is None and hi is None:
        return "all_real_numbers"
    if lo is None or hi is None:
        return "unbounded_half_line"
    return "point" if lo == hi else "bounded"


def fieller_reduction(method_means: list[float], control_means: list[float], alpha: float = .05) -> dict:
    """Paired Fieller confidence set for1-mean(method)/mean(control).

    Solve A*r^2+B*r+C<=0 for the method/control ratio then reflect around1.
    Unbounded/disjoint sets are returned verbatim as JSON-safe interval unions.
    These are descriptive intervals, not extra primary hypothesis tests.
    """
    if len(method_means) != len(control_means) or len(method_means) < 2 or not 0 < alpha < 1:
        raise ValueError("Aligned pairs and0<alpha<1 required")
    n = len(method_means)
    x, y = mean(method_means), mean(control_means)
    vxx, vyy = variance(method_means)/n, variance(control_means)/n
    vxy = covariance(method_means, control_means)/n
    critical2 = float(t.ppf(1-alpha/2, n-1))**2
    A = y*y-critical2*vyy
    B = -2*(x*y-critical2*vxy)
    C = x*x-critical2*vxx
    tolerance = 1e-12*max(1, abs(A), abs(B), abs(C))
    if abs(A) <= tolerance:
        if abs(B) <= tolerance:
            ratios = [[None, None]] if C <= tolerance else []
        else:
            root = -C/B
            ratios = [[None, root]] if B > 0 else [[root, None]]
    else:
        discriminant = B*B-4*A*C
        tolerance_d = 1e-12*max(1, B*B, abs(4*A*C))
        if discriminant < -tolerance_d:
            ratios = [[None, None]] if A < 0 else []
        else:
            discriminant = max(0.0, discriminant)
            roots = sorted(((-B-sqrt(discriminant))/(2*A), (-B+sqrt(discriminant))/(2*A)))
            ratios = [roots] if A > 0 else [[None, roots[0]], [roots[1], None]]
    reductions = _merge_intervals([[None if hi is None else 1-hi, None if lo is None else 1-lo] for lo, hi in ratios])
    return {"point_estimate": reduction_point(method_means, control_means), "alpha": alpha,
            "kind": _interval_kind(reductions), "intervals": reductions, "endpoint_None_means_unbounded": True,
            "A": A, "B": B, "C": C, "descriptive_only": True, "negative_reductions_clipped": False}


def average_reduction_sets(first: dict, second: dict) -> dict:
    """Equal-weight sum of two97.5%Fieller sets, descriptive >=95% by union bound."""
    intervals = []
    for a, b in [(a, b) for a in first["intervals"] for b in second["intervals"]]:
        lo = None if a[0] is None or b[0] is None else (a[0]+b[0])/2
        hi = None if a[1] is None or b[1] is None else (a[1]+b[1])/2
        intervals.append([lo, hi])
    result = _merge_intervals(intervals)
    return {"kind": _interval_kind(result), "intervals": result, "weights": [.5, .5],
            "construction": "Minkowski_sum_of_two_97p5_percent_Fieller_sets; approximate_descriptive95_percent",
            "descriptive_only": True, "negative_reductions_clipped": False}
