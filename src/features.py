"""Past-only market-state feature pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EPS, ModelConfig
from .normalization import robust_zero_score, robust_z_centered
from .positioning import classify_positioning, significance_state
from .states import add_state_columns


def true_range(frame: pd.DataFrame) -> pd.Series:
    """Calculate true range, resetting previous close at each segment start."""

    previous_close = frame.groupby("segment_id", sort=False)["close"].shift(1)
    candidates = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    values = candidates.max(axis=1, skipna=True)
    required = frame[["high", "low"]].notna().all(axis=1)
    return values.where(required)


def _wilder_group(values: pd.Series, period: int) -> pd.Series:
    output = pd.Series(np.nan, index=values.index, dtype="float64")
    valid_run: list[float] = []
    previous_atr = np.nan
    for index, value in values.items():
        if pd.isna(value):
            valid_run = []
            previous_atr = np.nan
            continue
        numeric_value = float(value)
        if np.isnan(previous_atr):
            valid_run.append(numeric_value)
            if len(valid_run) == period:
                previous_atr = float(np.mean(valid_run))
                output.loc[index] = previous_atr
        else:
            previous_atr = (
                (period - 1) * previous_atr + numeric_value
            ) / period
            output.loc[index] = previous_atr
    return output


def wilder_atr(
    true_range_values: pd.Series,
    period: int,
    segment_id: pd.Series | None = None,
) -> pd.Series:
    """Calculate Wilder ATR with an arithmetic seed and segment restarts."""

    if segment_id is None:
        return _wilder_group(true_range_values, period)
    output = pd.Series(np.nan, index=true_range_values.index, dtype="float64")
    for _, positions in segment_id.groupby(segment_id, sort=False).groups.items():
        output.loc[positions] = _wilder_group(
            true_range_values.loc[positions], period
        )
    return output


def _valid_ohlc_rows(frame: pd.DataFrame) -> pd.Series:
    ohlc = frame[["open", "high", "low", "close"]]
    return (
        ohlc.notna().all(axis=1)
        & ohlc.gt(0).all(axis=1)
        & frame["high"].ge(frame[["open", "close"]].max(axis=1))
        & frame["low"].le(frame[["open", "close"]].min(axis=1))
        & frame["high"].ge(frame["low"])
    )


def build_derived_features(
    frame: pd.DataFrame,
    config: ModelConfig | None = None,
) -> pd.DataFrame:
    """Build all state features using only information available at each bar."""

    config = config or ModelConfig()
    result = frame.copy()
    segment = result["segment_id"]
    valid_ohlc = _valid_ohlc_rows(result)
    valid_volume = result["volume"].notna() & result["volume"].ge(0)
    valid_oi = result["oi"].notna() & result["oi"].gt(0)

    result["true_range"] = true_range(result).where(valid_ohlc)
    atr = wilder_atr(result["true_range"], config.atr_period, segment)
    result["atr_ref"] = atr.groupby(segment, sort=False).shift(1)

    result["effort_raw"] = np.log1p(result["volume"]).where(valid_volume)
    result["effort_score"] = robust_z_centered(
        result["effort_raw"],
        config.normalization_window,
        config.min_reference_bars,
        segment,
    )

    body = (result["close"] - result["open"]).abs()
    range_value = (result["high"] - result["low"]).clip(lower=EPS)
    result["directional_efficiency"] = (body / range_value).clip(
        0.0, 1.0
    ).where(valid_ohlc)
    result["displacement"] = (body / result["atr_ref"]).where(
        result["atr_ref"].gt(EPS)
    )
    result["result_raw"] = result["displacement"] * (
        0.5 + 0.5 * result["directional_efficiency"]
    )
    result["result_score"] = robust_z_centered(
        result["result_raw"],
        config.normalization_window,
        config.min_reference_bars,
        segment,
    )

    price_change = result["close"] - result["open"]
    result["bar_direction"] = pd.Series(
        np.sign(price_change), index=result.index
    ).mask(~valid_ohlc).astype("Int8")
    previous_close = result.groupby(segment, sort=False)["close"].shift(1)
    previous_oi = result.groupby(segment, sort=False)["oi"].shift(1)
    result["price_log_return"] = np.log(result["close"] / previous_close).where(
        valid_ohlc & previous_close.gt(0)
    )
    result["delta_ratio"] = (result["delta"] / result["volume"]).where(
        valid_volume & result["delta"].notna() & result["volume"].gt(0)
    )
    result["oi_log_change"] = np.log(result["oi"] / previous_oi).where(
        valid_oi & previous_oi.gt(0)
    )

    score_arguments = (
        config.normalization_window,
        config.min_reference_bars,
        segment,
    )
    result["price_significance"] = robust_zero_score(
        result["price_log_return"], *score_arguments
    )
    result["delta_significance"] = robust_zero_score(
        result["delta_ratio"], *score_arguments
    )
    result["oi_significance"] = robust_zero_score(
        result["oi_log_change"], *score_arguments
    )
    result["price_state"] = significance_state(
        result["price_significance"], config.positioning_threshold
    )
    result["delta_state"] = significance_state(
        result["delta_significance"], config.positioning_threshold
    )
    result["oi_state"] = significance_state(
        result["oi_significance"], config.positioning_threshold
    )
    result["positioning_state"] = classify_positioning(
        result["price_state"], result["delta_state"], result["oi_state"]
    )
    return add_state_columns(result, config)
