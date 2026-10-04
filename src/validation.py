"""Historical forward-outcome validation with non-overlapping samples."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .config import EPS, ModelConfig
from .positioning import POSITIONING_STATES
from .states import EFFORT_RESULT_REGIONS
from .statistics import (
    bootstrap_difference_interval,
    bootstrap_mean_distribution,
    bootstrap_mean_interval,
    distribution_diagnostics,
    sample_quality,
    wilson_interval,
)


V011_VALIDATION_COLUMNS = (
    "Group Type",
    "Group",
    "Positioning State",
    "Event Direction",
    "Horizon",
    "Raw N",
    "Non-Overlapping N",
    "Sample Count",
    "Mean Forward Return",
    "Median Forward Return",
    "Mean Forward Bps",
    "Mean Forward ATR",
    "Median Forward ATR",
    "Positive Rate",
    "Median MFE ATR",
    "Median MAE ATR",
    "MFE >= 1 ATR",
    "MAE <= -1 ATR",
    "Baseline N",
    "Baseline Mean Return",
    "Baseline Median Return",
    "Baseline Positive Rate",
    "Baseline Mean ATR",
    "Baseline Median ATR",
    "Mean Return Difference",
    "Median Return Difference",
    "Positive Rate Difference",
    "Mean Difference",
    "95% CI Low",
    "95% CI High",
    "Positive Rate 95% CI Low",
    "Positive Rate 95% CI High",
    "Oriented Win Rate",
    "Mean Oriented Forward ATR",
    "Median Oriented Forward ATR",
    "Median Oriented MFE ATR",
    "Median Oriented MAE ATR",
    "Sample Quality",
)

V012_VALIDATION_COLUMNS = (
    "Event Frequency %",
    "Positioning State Frequency %",
    "Forward ATR 25th Percentile",
    "Forward ATR 50th Percentile",
    "Forward ATR 75th Percentile",
    "Forward Return 95% CI Low",
    "Forward Return 95% CI High",
    "Mean ATR Difference vs Baseline",
    "Difference vs Baseline ATR 95% CI Low",
    "Difference vs Baseline ATR 95% CI High",
    "Mean vs Median Divergence",
    "Mean vs Median Divergence Warning",
    "Tail-Driven Result Warning",
)


@dataclass(frozen=True, slots=True)
class ValidationGroup:
    """A named occurrence mask and optional research direction."""

    group_type: str
    group: str
    positioning_state: str
    mask: pd.Series
    event_direction: int = 0


def calculate_forward_outcomes(
    frame: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    """Calculate forward returns and excursions without crossing segments."""

    columns = (
        "forward_return",
        "forward_bps",
        "forward_atr",
        "mfe_atr",
        "mae_atr",
    )
    output = pd.DataFrame(np.nan, index=frame.index, columns=columns)
    for _, positions in frame.groupby("segment_id", sort=False).groups.items():
        indices = list(positions)
        for offset in range(0, len(indices) - horizon):
            current_index = indices[offset]
            future_indices = indices[offset + 1 : offset + horizon + 1]
            final_index = indices[offset + horizon]
            close = frame.at[current_index, "close"]
            future_close = frame.at[final_index, "close"]
            atr_ref = frame.at[current_index, "atr_ref"]
            future_high = frame.loc[future_indices, "high"].max(skipna=False)
            future_low = frame.loc[future_indices, "low"].min(skipna=False)
            if (
                pd.isna(close)
                or pd.isna(future_close)
                or pd.isna(atr_ref)
                or float(close) <= 0
                or float(future_close) <= 0
                or float(atr_ref) <= EPS
                or pd.isna(future_high)
                or pd.isna(future_low)
            ):
                continue
            forward_return = math.log(float(future_close) / float(close))
            output.at[current_index, "forward_return"] = forward_return
            output.at[current_index, "forward_bps"] = 10_000.0 * forward_return
            output.at[current_index, "forward_atr"] = (
                float(future_close) - float(close)
            ) / float(atr_ref)
            output.at[current_index, "mfe_atr"] = (
                float(future_high) - float(close)
            ) / float(atr_ref)
            output.at[current_index, "mae_atr"] = (
                float(future_low) - float(close)
            ) / float(atr_ref)
    return output


def non_overlapping_indices(
    frame: pd.DataFrame,
    candidates: pd.Index,
    horizon: int,
) -> pd.Index:
    """Select an event, then skip the following H bars in the same segment."""

    candidate_set = set(candidates)
    selected: list[object] = []
    for _, positions in frame.groupby("segment_id", sort=False).groups.items():
        last_selected_position = -horizon - 1
        for segment_position, index in enumerate(positions):
            if index not in candidate_set:
                continue
            if segment_position > last_selected_position + horizon:
                selected.append(index)
                last_selected_position = segment_position
    return pd.Index(selected)


def _validation_groups(frame: pd.DataFrame) -> list[ValidationGroup]:
    groups: list[ValidationGroup] = []
    for region in EFFORT_RESULT_REGIONS:
        groups.append(
            ValidationGroup(
                "Effort-Result Region",
                str(region),
                "All",
                frame["effort_result_region"].eq(region),
            )
        )
    for positioning in POSITIONING_STATES:
        groups.append(
            ValidationGroup(
                "Positioning State",
                "All Regions",
                str(positioning),
                frame["positioning_state"].eq(positioning),
            )
        )
    for region in EFFORT_RESULT_REGIONS:
        for positioning in POSITIONING_STATES:
            mask = frame["effort_result_region"].eq(region) & frame[
                "positioning_state"
            ].eq(positioning)
            groups.append(
                ValidationGroup(
                    "Region × Positioning State",
                    str(region),
                    str(positioning),
                    mask,
                )
            )
    event_definitions = (
        ("lehr_short_pressure", "LEHR Short Pressure", 1),
        ("lehr_long_pressure", "LEHR Long Pressure", -1),
        ("helr_event", "HELR Event", 0),
    )
    for column, label, direction in event_definitions:
        groups.append(
            ValidationGroup(
                "Research Event",
                label,
                "All",
                frame[column].fillna(False).astype(bool),
                direction,
            )
        )
    return groups


def _finite_values(outcomes: pd.DataFrame, column: str) -> np.ndarray:
    values = outcomes[column].to_numpy(dtype="float64")
    return values[np.isfinite(values)]


def _mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else math.nan


def _median(values: np.ndarray) -> float:
    return float(np.median(values)) if values.size else math.nan


def _rate(mask: np.ndarray) -> float:
    return float(np.mean(mask)) if mask.size else math.nan


def _baseline(
    frame: pd.DataFrame,
    outcomes: pd.DataFrame,
    horizon: int,
    use_non_overlapping: bool,
) -> tuple[dict[str, float], np.ndarray]:
    raw_indices = outcomes.index[outcomes["forward_return"].notna()]
    selected_indices = (
        non_overlapping_indices(frame, raw_indices, horizon)
        if use_non_overlapping
        else raw_indices
    )
    selected = outcomes.loc[selected_indices]
    returns = _finite_values(selected, "forward_return")
    atr_returns = _finite_values(selected, "forward_atr")
    return (
        {
            "mean_return": _mean(returns),
            "median_return": _median(returns),
            "positive_rate": _rate(returns > 0),
            "mean_atr": _mean(atr_returns),
            "median_atr": _median(atr_returns),
            "n": float(len(selected_indices)),
        },
        atr_returns,
    )


def build_validation_summary(
    frame: pd.DataFrame,
    config: ModelConfig | None = None,
    *,
    non_overlapping: bool = True,
) -> pd.DataFrame:
    """Build group/horizon validation, baseline comparisons, and intervals."""

    config = config or ModelConfig()
    rows: list[dict[str, object]] = []
    for horizon in config.forward_horizons:
        outcomes = calculate_forward_outcomes(frame, horizon)
        valid_outcome = outcomes["forward_return"].notna()
        baseline, baseline_atr_returns = _baseline(
            frame, outcomes, horizon, non_overlapping
        )
        baseline_atr_bootstrap = bootstrap_mean_distribution(
            baseline_atr_returns,
            seed=config.random_seed + horizon * 100_000 + 50_000,
        )
        valid_outcome_count = int(valid_outcome.sum())
        for group_number, group in enumerate(_validation_groups(frame)):
            raw_indices = outcomes.index[group.mask & valid_outcome]
            non_overlap_indices = non_overlapping_indices(
                frame, raw_indices, horizon
            )
            selected_indices = (
                non_overlap_indices if non_overlapping else raw_indices
            )
            selected = outcomes.loc[selected_indices]
            returns = _finite_values(selected, "forward_return")
            atr_returns = _finite_values(selected, "forward_atr")
            mfe = _finite_values(selected, "mfe_atr")
            mae = _finite_values(selected, "mae_atr")
            positive_count = int(np.sum(returns > 0))
            positive_ci = wilson_interval(positive_count, returns.size)
            mean_ci = bootstrap_mean_interval(
                returns,
                seed=config.random_seed + horizon * 1_000 + group_number,
            )
            conditional_atr_bootstrap = bootstrap_mean_distribution(
                atr_returns,
                seed=config.random_seed + horizon * 100_000 + group_number,
            )
            difference_ci = bootstrap_difference_interval(
                conditional_atr_bootstrap,
                baseline_atr_bootstrap,
            )
            atr_diagnostics = distribution_diagnostics(atr_returns)

            oriented = (
                group.event_direction * atr_returns
                if group.event_direction
                else np.array([], dtype="float64")
            )
            oriented_win_rate = (
                _rate(oriented > 0) if group.event_direction else math.nan
            )
            if group.event_direction == 1:
                oriented_mfe, oriented_mae = mfe, mae
            elif group.event_direction == -1:
                oriented_mfe, oriented_mae = -mae, -mfe
            else:
                oriented_mfe = oriented_mae = np.array([], dtype="float64")

            mean_return = _mean(returns)
            median_return = _median(returns)
            positive_rate = _rate(returns > 0)
            mean_atr = _mean(atr_returns)
            median_atr = _median(atr_returns)
            mean_atr_difference = mean_atr - baseline["mean_atr"]
            event_frequency = (
                100.0 * len(raw_indices) / valid_outcome_count
                if group.group_type == "Research Event" and valid_outcome_count
                else math.nan
            )
            positioning_frequency = math.nan
            if group.positioning_state != "All" and valid_outcome_count:
                positioning_frequency = 100.0 * int(
                    (
                        frame["positioning_state"].eq(group.positioning_state)
                        & valid_outcome
                    ).sum()
                ) / valid_outcome_count
            rows.append(
                {
                    "Group Type": group.group_type,
                    "Group": group.group,
                    "Positioning State": group.positioning_state,
                    "Event Direction": group.event_direction,
                    "Horizon": horizon,
                    "Raw N": len(raw_indices),
                    "Non-Overlapping N": len(non_overlap_indices),
                    "Sample Count": len(selected_indices),
                    "Event Frequency %": event_frequency,
                    "Positioning State Frequency %": positioning_frequency,
                    "Mean Forward Return": mean_return,
                    "Median Forward Return": median_return,
                    "Mean Forward Bps": 10_000.0 * mean_return,
                    "Mean Forward ATR": mean_atr,
                    "Median Forward ATR": median_atr,
                    "Forward ATR 25th Percentile": (
                        atr_diagnostics.percentile_25
                    ),
                    "Forward ATR 50th Percentile": median_atr,
                    "Forward ATR 75th Percentile": (
                        atr_diagnostics.percentile_75
                    ),
                    "Positive Rate": positive_rate,
                    "Median MFE ATR": _median(mfe),
                    "Median MAE ATR": _median(mae),
                    "MFE >= 1 ATR": _rate(mfe >= 1.0),
                    "MAE <= -1 ATR": _rate(mae <= -1.0),
                    "Baseline N": int(baseline["n"]),
                    "Baseline Mean Return": baseline["mean_return"],
                    "Baseline Median Return": baseline["median_return"],
                    "Baseline Positive Rate": baseline["positive_rate"],
                    "Baseline Mean ATR": baseline["mean_atr"],
                    "Baseline Median ATR": baseline["median_atr"],
                    "Mean Return Difference": mean_return
                    - baseline["mean_return"],
                    "Median Return Difference": median_return
                    - baseline["median_return"],
                    "Positive Rate Difference": positive_rate
                    - baseline["positive_rate"],
                    "Mean Difference": mean_atr_difference,
                    "95% CI Low": mean_ci[0],
                    "95% CI High": mean_ci[1],
                    "Forward Return 95% CI Low": mean_ci[0],
                    "Forward Return 95% CI High": mean_ci[1],
                    "Mean ATR Difference vs Baseline": mean_atr_difference,
                    "Difference vs Baseline ATR 95% CI Low": difference_ci[0],
                    "Difference vs Baseline ATR 95% CI High": difference_ci[1],
                    "Positive Rate 95% CI Low": positive_ci[0],
                    "Positive Rate 95% CI High": positive_ci[1],
                    "Mean vs Median Divergence": (
                        atr_diagnostics.mean_median_divergence
                    ),
                    "Mean vs Median Divergence Warning": (
                        atr_diagnostics.mean_median_divergence_warning
                    ),
                    "Tail-Driven Result Warning": (
                        atr_diagnostics.tail_driven_result_warning
                    ),
                    "Oriented Win Rate": oriented_win_rate,
                    "Mean Oriented Forward ATR": _mean(oriented),
                    "Median Oriented Forward ATR": _median(oriented),
                    "Median Oriented MFE ATR": _median(oriented_mfe),
                    "Median Oriented MAE ATR": _median(oriented_mae),
                    "Sample Quality": sample_quality(len(selected_indices)),
                }
            )
    return pd.DataFrame(rows)[
        [*V011_VALIDATION_COLUMNS, *V012_VALIDATION_COLUMNS]
    ]
