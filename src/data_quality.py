"""Data-quality inspection and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "delta",
    "oi",
)
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume", "delta", "oi")


@dataclass(slots=True)
class QualityReport:
    """Dataset-level quality measurements suitable for the UI."""

    rows_loaded: int
    valid_rows: int
    first_timestamp: pd.Timestamp | None
    last_timestamp: pd.Timestamp | None
    expected_bar_interval: pd.Timedelta | None
    detected_gaps: int
    duplicate_timestamps: int
    missing_ohlc: int
    missing_volume: int
    missing_delta: int
    missing_oi: int
    delta_exceeds_volume: int
    invalid_ohlc: int
    invalid_volume: int
    invalid_oi: int
    segments: int
    warmup_rows: int = 0
    usable_state_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return labels matching the Data Quality page."""

        return {
            "Rows Loaded": self.rows_loaded,
            "Valid Rows": self.valid_rows,
            "First Timestamp": self.first_timestamp,
            "Last Timestamp": self.last_timestamp,
            "Expected Bar Interval": self.expected_bar_interval,
            "Detected Gaps": self.detected_gaps,
            "Duplicate Timestamps": self.duplicate_timestamps,
            "Missing OHLC": self.missing_ohlc,
            "Missing Volume": self.missing_volume,
            "Missing Delta": self.missing_delta,
            "Missing OI": self.missing_oi,
            "abs(Delta) > Volume count": self.delta_exceeds_volume,
            "Invalid OHLC count": self.invalid_ohlc,
            "Invalid Volume count": self.invalid_volume,
            "Invalid OI count": self.invalid_oi,
            "Segments": self.segments,
            "Warmup Rows": self.warmup_rows,
            "Usable State Rows": self.usable_state_rows,
        }


def add_quality_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach row-level quality flags without filling or interpolating values."""

    result = frame.copy()
    flags: list[list[str]] = [[] for _ in range(len(result))]

    def flag(mask: pd.Series | np.ndarray, name: str) -> None:
        for position in np.flatnonzero(np.asarray(mask, dtype=bool)):
            flags[position].append(name)

    flag(result["timestamp"].isna(), "missing_timestamp")
    flag(result.duplicated("timestamp", keep=False), "duplicate_timestamp")
    flag(result[list(("open", "high", "low", "close"))].isna().any(axis=1), "missing_ohlc")
    flag(result["volume"].isna(), "missing_volume")
    flag(result["delta"].isna(), "missing_delta")
    flag(result["oi"].isna(), "missing_oi")

    positive_ohlc = result[list(("open", "high", "low", "close"))].gt(0).all(axis=1)
    valid_relationships = (
        result["high"].ge(result["open"])
        & result["high"].ge(result["close"])
        & result["low"].le(result["open"])
        & result["low"].le(result["close"])
        & result["high"].ge(result["low"])
    )
    complete_ohlc = result[list(("open", "high", "low", "close"))].notna().all(axis=1)
    flag(complete_ohlc & ~(positive_ohlc & valid_relationships), "invalid_ohlc")
    flag(result["volume"].notna() & result["volume"].lt(0), "invalid_volume")
    flag(result["oi"].notna() & result["oi"].le(0), "invalid_oi")
    flag(
        result["delta"].notna()
        & result["volume"].notna()
        & result["delta"].abs().gt(result["volume"]),
        "delta_exceeds_volume",
    )
    result["data_quality_flag"] = [";".join(row_flags) for row_flags in flags]
    return result


def build_quality_report(frame: pd.DataFrame) -> QualityReport:
    """Summarize quality flags and segmentation metadata."""

    timestamps = frame["timestamp"].dropna()
    flags = frame["data_quality_flag"].fillna("")

    def count(name: str) -> int:
        return int(flags.str.split(";").apply(lambda values: name in values).sum())

    invalid_for_state = flags.str.contains(
        "missing_timestamp|duplicate_timestamp|missing_ohlc|missing_volume|"
        "missing_delta|missing_oi|invalid_ohlc|invalid_volume|invalid_oi",
        regex=True,
    )
    interval = frame.attrs.get("expected_bar_interval")
    segments = int(frame["segment_id"].nunique()) if "segment_id" in frame else 0
    gaps = int(frame.get("is_structural_gap", pd.Series(False, index=frame.index)).sum())
    return QualityReport(
        rows_loaded=len(frame),
        valid_rows=int((~invalid_for_state).sum()),
        first_timestamp=timestamps.min() if not timestamps.empty else None,
        last_timestamp=timestamps.max() if not timestamps.empty else None,
        expected_bar_interval=interval,
        detected_gaps=gaps,
        duplicate_timestamps=int(frame.duplicated("timestamp", keep=False).sum()),
        missing_ohlc=int(frame[list(("open", "high", "low", "close"))].isna().any(axis=1).sum()),
        missing_volume=int(frame["volume"].isna().sum()),
        missing_delta=int(frame["delta"].isna().sum()),
        missing_oi=int(frame["oi"].isna().sum()),
        delta_exceeds_volume=count("delta_exceeds_volume"),
        invalid_ohlc=count("invalid_ohlc"),
        invalid_volume=count("invalid_volume"),
        invalid_oi=count("invalid_oi"),
        segments=segments,
    )
