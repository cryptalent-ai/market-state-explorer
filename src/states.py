"""Effort-result region and research-event definitions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ModelConfig


EFFORT_RESULT_REGIONS = (
    "High Effort / High Result",
    "High Effort / Low Result",
    "Low Effort / High Result",
    "Low Effort / Low Result",
)


def classify_effort_result_region(
    effort: pd.Series,
    result: pd.Series,
) -> pd.Series:
    """Assign one of the four zero-boundary regions."""

    conditions = [
        effort.ge(0) & result.ge(0),
        effort.ge(0) & result.lt(0),
        effort.lt(0) & result.ge(0),
        effort.lt(0) & result.lt(0),
    ]
    values = np.select(conditions, EFFORT_RESULT_REGIONS, default="Unavailable")
    return pd.Series(values, index=effort.index, dtype="string")


def add_state_columns(frame: pd.DataFrame, config: ModelConfig) -> pd.DataFrame:
    """Attach region, strength, trajectory diagnostics, and event flags."""

    result = frame.copy()
    effort = result["effort_score"]
    result_score = result["result_score"]
    result["effort_result_region"] = classify_effort_result_region(
        effort, result_score
    )
    boundary = effort.abs().lt(config.boundary_threshold) | result_score.abs().lt(
        config.boundary_threshold
    )
    result["near_state_boundary"] = boundary.mask(
        effort.isna() | result_score.isna()
    ).astype("boolean")
    result["state_strength"] = np.sqrt(effort.pow(2) + result_score.pow(2))

    effort_change = result.groupby("segment_id", sort=False)["effort_score"].diff()
    result_change = result.groupby("segment_id", sort=False)["result_score"].diff()
    result["state_velocity"] = np.sqrt(
        effort_change.pow(2) + result_change.pow(2)
    )
    result["state_acceleration"] = result.groupby(
        "segment_id", sort=False
    )["state_velocity"].diff()

    result["lehr_short_pressure"] = (
        effort.le(config.low_effort_threshold)
        & result_score.ge(config.high_result_threshold)
        & result["price_state"].eq(1)
        & result["delta_state"].eq(-1)
        & result["oi_state"].eq(1)
    )
    result["lehr_long_pressure"] = (
        effort.le(config.low_effort_threshold)
        & result_score.ge(config.high_result_threshold)
        & result["price_state"].eq(-1)
        & result["delta_state"].eq(1)
        & result["oi_state"].eq(1)
    )
    result["helr_event"] = effort.ge(
        config.high_effort_threshold
    ) & result_score.le(config.low_result_threshold)
    return result
