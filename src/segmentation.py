"""Timestamp interval estimation and contiguous-segment assignment."""

from __future__ import annotations

import pandas as pd


def add_segments(frame: pd.DataFrame) -> pd.DataFrame:
    """Start a new segment after intervals over 1.5 times the median interval."""

    result = frame.copy()
    differences = result["timestamp"].diff()
    positive_differences = differences[differences > pd.Timedelta(0)]
    expected = (
        positive_differences.median() if not positive_differences.empty else None
    )
    if expected is None or pd.isna(expected):
        gaps = pd.Series(False, index=result.index)
    else:
        gaps = differences.gt(expected * 1.5).fillna(False)
    result["is_structural_gap"] = gaps.astype(bool)
    result["segment_id"] = gaps.cumsum().astype("int64")
    result.attrs.update(frame.attrs)
    result.attrs["expected_bar_interval"] = expected
    return result
