"""Strictly backward Open Interest alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd


def align_open_interest(
    bars: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    max_oi_age_seconds: int = 300,
    exact_tolerance_seconds: float = 1.0,
    preferred_age_seconds: float = 60.0,
) -> pd.DataFrame:
    """Assign the latest OI period-end observation no later than bar close."""

    if max_oi_age_seconds < 0:
        raise ValueError("Maximum OI age cannot be negative")
    left = bars.copy().sort_values("bar_close_timestamp", kind="stable")
    right = observations.copy().sort_values("oi_source_timestamp", kind="stable")
    right = right.drop_duplicates("oi_source_timestamp", keep="last")
    if right.empty:
        result = left.copy()
        result["oi"] = np.nan
        result["oi_source_timestamp"] = pd.Series(
            pd.NaT, index=result.index, dtype="datetime64[ns, UTC]"
        )
    else:
        result = pd.merge_asof(
            left,
            right[["oi_source_timestamp", "oi"]],
            left_on="bar_close_timestamp",
            right_on="oi_source_timestamp",
            direction="backward",
            allow_exact_matches=True,
            tolerance=pd.to_timedelta(max_oi_age_seconds, unit="s"),
        )
    result["oi_age_seconds"] = (
        result["bar_close_timestamp"] - result["oi_source_timestamp"]
    ).dt.total_seconds()
    future = result["oi_age_seconds"].lt(0).fillna(False)
    result["future_oi_match"] = future.astype(bool)
    result.loc[future, ["oi", "oi_source_timestamp", "oi_age_seconds"]] = [
        np.nan,
        pd.NaT,
        np.nan,
    ]
    age = result["oi_age_seconds"]
    result["oi_alignment_quality"] = np.select(
        [
            result["oi"].isna(),
            age.le(exact_tolerance_seconds),
            age.le(preferred_age_seconds),
        ],
        ["MISSING", "EXACT", "RECENT"],
        default="STALE",
    )
    missing_flag = result["oi_alignment_quality"].eq("MISSING")
    stale_flag = result["oi_alignment_quality"].eq("STALE")
    existing = result.get(
        "builder_data_quality_flag", pd.Series("", index=result.index)
    ).fillna("")
    result["builder_data_quality_flag"] = existing
    result.loc[missing_flag, "builder_data_quality_flag"] = result.loc[
        missing_flag, "builder_data_quality_flag"
    ].apply(lambda value: _append_flag(value, "MISSING_OI"))
    result.loc[stale_flag, "builder_data_quality_flag"] = result.loc[
        stale_flag, "builder_data_quality_flag"
    ].apply(lambda value: _append_flag(value, "STALE_OI"))
    result["data_quality_flag"] = result["builder_data_quality_flag"]
    return result.sort_values("timestamp", kind="stable").reset_index(drop=True)


def _append_flag(existing: str, flag: str) -> str:
    return f"{existing};{flag}" if existing else flag
