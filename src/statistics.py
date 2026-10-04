"""Small-sample labels and deterministic confidence intervals."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


def wilson_interval(
    successes: int,
    total: int,
    confidence_z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Return a two-sided Wilson confidence interval for a proportion."""

    if total <= 0:
        return (math.nan, math.nan)
    proportion = successes / total
    z_squared = confidence_z**2
    denominator = 1.0 + z_squared / total
    center = (proportion + z_squared / (2.0 * total)) / denominator
    radius = (
        confidence_z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z_squared / (4.0 * total**2)
        )
        / denominator
    )
    return (max(0.0, center - radius), min(1.0, center + radius))


def bootstrap_mean_interval(
    values: np.ndarray,
    *,
    seed: int = 42,
    samples: int = 2_000,
) -> tuple[float, float]:
    """Return a percentile bootstrap 95% interval for the arithmetic mean."""

    clean = np.asarray(values, dtype="float64")
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return (math.nan, math.nan)
    if clean.size == 1:
        value = float(clean[0])
        return (value, value)
    generator = np.random.default_rng(seed)
    means = np.empty(samples, dtype="float64")
    chunk = max(1, min(200, 1_000_000 // clean.size))
    for start in range(0, samples, chunk):
        stop = min(start + chunk, samples)
        draws = generator.choice(clean, size=(stop - start, clean.size), replace=True)
        means[start:stop] = draws.mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return (float(low), float(high))


def bootstrap_mean_distribution(
    values: np.ndarray,
    *,
    seed: int = 42,
    samples: int = 2_000,
) -> np.ndarray:
    """Return deterministic bootstrap draws of an arithmetic mean."""

    clean = np.asarray(values, dtype="float64")
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return np.array([], dtype="float64")
    if clean.size == 1:
        return np.full(samples, float(clean[0]), dtype="float64")
    generator = np.random.default_rng(seed)
    means = np.empty(samples, dtype="float64")
    chunk = max(1, min(200, 1_000_000 // clean.size))
    for start in range(0, samples, chunk):
        stop = min(start + chunk, samples)
        draws = generator.choice(clean, size=(stop - start, clean.size), replace=True)
        means[start:stop] = draws.mean(axis=1)
    return means


def bootstrap_difference_interval(
    conditional_mean_draws: np.ndarray,
    baseline_mean_draws: np.ndarray,
) -> tuple[float, float]:
    """Return a percentile CI for conditional mean minus baseline mean."""

    conditional = np.asarray(conditional_mean_draws, dtype="float64")
    baseline = np.asarray(baseline_mean_draws, dtype="float64")
    if conditional.size == 0 or baseline.size == 0:
        return (math.nan, math.nan)
    if conditional.size != baseline.size:
        raise ValueError("Bootstrap distributions must contain the same draws")
    differences = conditional - baseline
    low, high = np.quantile(differences, [0.025, 0.975])
    return (float(low), float(high))


@dataclass(frozen=True, slots=True)
class DistributionDiagnostics:
    """Robust location diagnostics for a forward-ATR distribution."""

    percentile_25: float
    percentile_50: float
    percentile_75: float
    mean_median_divergence: float
    mean_median_divergence_warning: bool
    tail_driven_result_warning: bool


def distribution_diagnostics(values: np.ndarray) -> DistributionDiagnostics:
    """Describe central spread and flag means that may be tail-sensitive.

    Mean/median divergence is flagged when their distance exceeds half the
    interquartile range. A result is tail-driven when its mean falls outside
    the central 50% interval or its sign differs from the median. These are
    transparent diagnostics, not model or event-selection thresholds.
    """

    clean = np.asarray(values, dtype="float64")
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return DistributionDiagnostics(
            math.nan,
            math.nan,
            math.nan,
            math.nan,
            False,
            False,
        )
    percentile_25, percentile_50, percentile_75 = np.quantile(
        clean, [0.25, 0.5, 0.75]
    )
    mean = float(np.mean(clean))
    median = float(percentile_50)
    divergence = mean - median
    iqr = float(percentile_75 - percentile_25)
    tolerance = np.finfo("float64").eps * max(
        1.0,
        abs(mean),
        abs(median),
        abs(float(percentile_25)),
        abs(float(percentile_75)),
    )
    divergence_warning = abs(divergence) > max(0.5 * iqr, tolerance)
    sign_divergence = (
        abs(mean) > tolerance
        and abs(median) > tolerance
        and np.signbit(mean) != np.signbit(median)
    )
    tail_driven = bool(
        mean < float(percentile_25) - tolerance
        or mean > float(percentile_75) + tolerance
        or sign_divergence
    )
    return DistributionDiagnostics(
        float(percentile_25),
        median,
        float(percentile_75),
        float(divergence),
        bool(divergence_warning),
        tail_driven,
    )


def sample_quality(sample_count: int) -> str:
    """Use deliberately neutral research-readiness terminology."""

    if sample_count < 30:
        return "Insufficient sample"
    if sample_count < 100:
        return "Exploratory"
    return "Usable research sample"
