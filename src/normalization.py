"""Past-only robust rolling normalization."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from .config import EPS


def _median_absolute_deviation(values: np.ndarray) -> float:
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)))


def _rolling_reference(
    series: pd.Series,
    window: int,
    min_periods: int,
) -> tuple[pd.Series, pd.Series]:
    """Return historical median and robust/fallback scale, excluding current."""

    history = series.shift(1)
    rolling = history.rolling(window=window, min_periods=min_periods)
    median = rolling.median()
    mad = rolling.apply(_median_absolute_deviation, raw=True)
    robust_scale = 1.4826 * mad
    fallback = rolling.std(ddof=0)
    scale = robust_scale.where(robust_scale.ge(EPS), fallback)
    scale = scale.where(scale.ge(EPS), np.nan)
    return median, scale


def _by_segment(
    series: pd.Series,
    segment_id: pd.Series | None,
    operation: Callable[[pd.Series], pd.Series],
) -> pd.Series:
    if segment_id is None:
        return operation(series)
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    for _, positions in segment_id.groupby(segment_id, sort=False).groups.items():
        result.loc[positions] = operation(series.loc[positions])
    return result


def robust_z_centered(
    series: pd.Series,
    window: int,
    min_periods: int,
    segment_id: pd.Series | None = None,
) -> pd.Series:
    """Centered robust z-score using only t-W through t-1 as reference."""

    numeric = pd.to_numeric(series, errors="coerce").astype("float64")

    def calculate(group: pd.Series) -> pd.Series:
        median, scale = _rolling_reference(group, window, min_periods)
        score = (group - median) / scale
        no_scale = scale.isna() & median.notna() & group.notna()
        score = score.mask(no_scale, 0.0)
        return score.clip(-8.0, 8.0)

    return _by_segment(numeric, segment_id, calculate)


def robust_zero_score(
    series: pd.Series,
    window: int,
    min_periods: int,
    segment_id: pd.Series | None = None,
) -> pd.Series:
    """Zero-centered significance score with a past-only robust scale."""

    numeric = pd.to_numeric(series, errors="coerce").astype("float64")

    def calculate(group: pd.Series) -> pd.Series:
        median, scale = _rolling_reference(group, window, min_periods)
        score = group / scale
        no_scale = scale.isna() & median.notna() & group.notna()
        score = score.mask(no_scale, 0.0)
        return score.clip(-8.0, 8.0)

    return _by_segment(numeric, segment_id, calculate)
