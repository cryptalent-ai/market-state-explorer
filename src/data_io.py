"""CSV loading, coercion, and explicit integrity handling."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
from os import PathLike
from typing import BinaryIO, TextIO

import pandas as pd

from .data_quality import (
    NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
    QualityReport,
    add_quality_flags,
    build_quality_report,
)
from .segmentation import add_segments


@dataclass(slots=True)
class MarketData:
    """Prepared calculation frame plus an untouched source copy."""

    frame: pd.DataFrame
    raw: pd.DataFrame
    quality: QualityReport


class DataValidationError(ValueError):
    """Fatal data-contract error with optional inspected data attached."""

    def __init__(
        self,
        message: str,
        *,
        report: QualityReport | None = None,
        frame: pd.DataFrame | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report
        self.frame = frame


CsvSource = str | PathLike[str] | TextIO | BinaryIO | StringIO | BytesIO


def parse_timestamp(series: pd.Series) -> pd.Series:
    """Parse ISO-8601, Unix-second, or Unix-millisecond timestamps to UTC."""

    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return pd.to_datetime(series, utc=True, errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return pd.to_datetime(series, utc=True, errors="coerce")
    numeric = pd.to_numeric(series, errors="coerce")
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    numeric_mask = numeric.notna()
    if numeric_mask.any():
        millisecond_mask = numeric_mask & numeric.abs().ge(1e11)
        second_mask = numeric_mask & ~millisecond_mask
        result.loc[millisecond_mask] = pd.to_datetime(
            numeric.loc[millisecond_mask], unit="ms", utc=True, errors="coerce"
        )
        result.loc[second_mask] = pd.to_datetime(
            numeric.loc[second_mask], unit="s", utc=True, errors="coerce"
        )
    text_mask = ~numeric_mask & series.notna()
    if text_mask.any():
        result.loc[text_mask] = pd.to_datetime(
            series.loc[text_mask], utc=True, errors="coerce"
        )
    return result


def prepare_market_data(raw: pd.DataFrame) -> MarketData:
    """Validate and prepare a raw market-data frame without fabricating values."""

    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        raise DataValidationError(
            "Missing required columns: " + ", ".join(sorted(missing))
        )

    source_copy = raw.copy(deep=True)
    frame = raw.copy()
    frame["timestamp"] = parse_timestamp(frame["timestamp"])
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values("timestamp", kind="stable", na_position="last")
    frame = frame.reset_index(drop=True)
    frame = add_segments(frame)
    frame = add_quality_flags(frame)
    report = build_quality_report(frame)

    if frame["timestamp"].isna().any():
        raise DataValidationError(
            "One or more timestamps could not be parsed.",
            report=report,
            frame=frame,
        )
    if report.duplicate_timestamps:
        raise DataValidationError(
            "Duplicate timestamps are unresolved; the file was rejected.",
            report=report,
            frame=frame,
        )
    return MarketData(frame=frame, raw=source_copy, quality=report)


def load_market_csv(source: CsvSource, **read_csv_kwargs: object) -> MarketData:
    """Read a CSV source and apply the market-data contract."""

    raw = pd.read_csv(source, **read_csv_kwargs)
    return prepare_market_data(raw)
