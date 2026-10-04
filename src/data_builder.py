"""Native BTCUSDT dataset orchestration, quality, and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .dataset_metadata import (
    DatasetMetadata,
    create_metadata,
    unique_output_path,
)
from .delta import reconstruct_delta
from .oi_alignment import align_open_interest
from .providers.base import MarketDataProvider, ProgressCallback


BAR_SECONDS = 300
BAR_INTERVAL = pd.to_timedelta(BAR_SECONDS, unit="s")


class DatasetStatus(StrEnum):
    VALID = "VALID"
    USABLE_WITH_WARNINGS = "USABLE_WITH_WARNINGS"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class BuildRequest:
    start_date: date
    end_date: date
    max_oi_age_seconds: int = 300
    research_kline_coverage: float = 0.999
    research_oi_coverage: float = 0.99
    minimum_usable_kline_coverage: float = 0.99
    minimum_usable_oi_coverage: float = 0.90

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("End date must not precede start date")
        if self.max_oi_age_seconds < 0:
            raise ValueError("Maximum OI age cannot be negative")


@dataclass(slots=True)
class BuilderQualityReport:
    requested_bars: int
    received_klines: int
    missing_klines: int
    duplicate_klines: int
    invalid_ohlc_rows: int
    off_grid_klines: int
    delta_valid_rows: int
    delta_invalid_rows: int
    oi_source_rows: int
    oi_matched_rows: int
    oi_missing_rows: int
    oi_stale_rows: int
    oi_coverage: float
    kline_coverage: float
    maximum_oi_age: float | None
    median_oi_age: float | None
    future_oi_matches: int
    detected_gaps: int
    segments: int
    available_kline_start: str | None
    available_kline_end: str | None
    available_oi_start: str | None
    available_oi_end: str | None
    missing_kline_source_dates: list[str] = field(default_factory=list)
    missing_oi_source_dates: list[str] = field(default_factory=list)
    status: DatasetStatus = DatasetStatus.INVALID
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "Requested Bars": self.requested_bars,
            "Received Klines": self.received_klines,
            "Missing Klines": self.missing_klines,
            "Duplicate Klines": self.duplicate_klines,
            "Invalid OHLC Rows": self.invalid_ohlc_rows,
            "Off-grid Klines": self.off_grid_klines,
            "Kline Coverage %": round(100.0 * self.kline_coverage, 6),
            "Delta Valid Rows": self.delta_valid_rows,
            "Delta Invalid Rows": self.delta_invalid_rows,
            "OI Source Rows": self.oi_source_rows,
            "OI Matched Rows": self.oi_matched_rows,
            "OI Missing Rows": self.oi_missing_rows,
            "OI Stale Rows": self.oi_stale_rows,
            "OI Coverage %": round(100.0 * self.oi_coverage, 6),
            "Maximum OI Age": self.maximum_oi_age,
            "Median OI Age": self.median_oi_age,
            "Future OI Matches": self.future_oi_matches,
            "Detected Gaps": self.detected_gaps,
            "Segments": self.segments,
            "Available Kline Start": self.available_kline_start,
            "Available Kline End": self.available_kline_end,
            "Available OI Start": self.available_oi_start,
            "Available OI End": self.available_oi_end,
            "Missing Kline Source Dates": self.missing_kline_source_dates,
            "Missing OI Source Dates": self.missing_oi_source_dates,
            "Dataset Status": self.status.value,
            "Warnings": self.warnings,
        }


@dataclass(slots=True)
class BuildResult:
    dataset: pd.DataFrame
    metadata: DatasetMetadata
    quality: BuilderQualityReport
    processed_path: Path
    metadata_path: Path

    @property
    def can_use_in_explorer(self) -> bool:
        return self.quality.status is not DatasetStatus.INVALID


class NativeDataBuilder:
    """Build an auditable v0.1-compatible dataset from an isolated provider."""

    def __init__(
        self,
        provider: MarketDataProvider,
        storage_root: Path,
    ) -> None:
        self.provider = provider
        self.storage_root = storage_root

    def build(
        self,
        request: BuildRequest,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        emit = progress or (lambda _: None)
        emit("Checking official source...")

        emit("Downloading Klines...")
        klines = self.provider.fetch_klines(
            request.start_date, request.end_date, progress
        )

        emit("Downloading Open Interest...")
        # The final 23:55 bar closes at next-day 00:00, so acquire that
        # period-end boundary explicitly rather than using an earlier/future proxy.
        oi = self.provider.fetch_open_interest(
            request.start_date,
            request.end_date + timedelta(days=1),
            progress,
        )
        end_exclusive = pd.Timestamp(
            request.end_date + timedelta(days=1), tz="UTC"
        )
        oi_for_alignment = oi.data[
            oi.data["oi_source_timestamp"].le(end_exclusive)
        ].copy()

        emit("Validating Klines...")
        source_klines = klines.data.sort_values("timestamp", kind="stable").reset_index(
            drop=True
        )

        emit("Reconstructing Delta...")
        with_delta = reconstruct_delta(source_klines)

        emit("Aligning Open Interest...")
        aligned = align_open_interest(
            with_delta,
            oi_for_alignment,
            max_oi_age_seconds=request.max_oi_age_seconds,
        )
        aligned["open_time"] = aligned["timestamp"]
        aligned["symbol"] = "BTCUSDT"
        aligned["exchange"] = "Binance USDT-M"
        aligned["timeframe"] = "5m"

        emit("Running Data Quality checks...")
        quality = self._quality(
            aligned,
            oi_for_alignment,
            request,
            [value.isoformat() for value in klines.missing_dates],
            [value.isoformat() for value in oi.missing_dates],
        )

        emit("Saving processed dataset...")
        filename_base = (
            f"BTCUSDT_USDTM_5m_{request.start_date:%Y%m%d}_"
            f"{request.end_date:%Y%m%d}"
        )
        processed_path = unique_output_path(
            self.storage_root / "processed" / "BTCUSDT_5m",
            f"{filename_base}.csv",
        )
        metadata_path = unique_output_path(
            self.storage_root / "metadata", f"{filename_base}.json"
        )
        metadata = create_metadata(
            provider_metadata=self.provider.source_metadata(),
            start=request.start_date.isoformat(),
            end=request.end_date.isoformat(),
            rows=len(aligned),
            quality=quality.as_dict(),
            kline_sources=klines.source_urls,
            oi_sources=oi.source_urls,
            cache_hits=klines.cache_hits + oi.cache_hits,
            downloads=klines.downloads + oi.downloads,
            max_oi_age_seconds=request.max_oi_age_seconds,
        )
        aligned.to_csv(processed_path, index=False)
        metadata_path.write_text(metadata.to_json(), encoding="utf-8")
        emit("Complete.")
        return BuildResult(
            dataset=aligned,
            metadata=metadata,
            quality=quality,
            processed_path=processed_path,
            metadata_path=metadata_path,
        )

    @staticmethod
    def _quality(
        dataset: pd.DataFrame,
        oi_source: pd.DataFrame,
        request: BuildRequest,
        missing_kline_dates: list[str],
        missing_oi_dates: list[str],
    ) -> BuilderQualityReport:
        start = pd.Timestamp(request.start_date, tz="UTC")
        end_exclusive = pd.Timestamp(
            request.end_date + timedelta(days=1), tz="UTC"
        )
        expected = pd.date_range(
            start, end_exclusive - BAR_INTERVAL, freq=BAR_INTERVAL, tz="UTC"
        )
        timestamps = dataset["timestamp"]
        duplicate_klines = int(timestamps.duplicated(keep="first").sum())
        unique_timestamps = pd.DatetimeIndex(timestamps.drop_duplicates())
        missing_klines = len(expected.difference(unique_timestamps))
        off_grid = len(unique_timestamps.difference(expected))

        ohlc = dataset[["open", "high", "low", "close"]]
        valid_ohlc = (
            ohlc.notna().all(axis=1)
            & ohlc.gt(0).all(axis=1)
            & dataset["high"].ge(dataset[["open", "close"]].max(axis=1))
            & dataset["low"].le(dataset[["open", "close"]].min(axis=1))
            & dataset["high"].ge(dataset["low"])
        )
        invalid_ohlc = int((~valid_ohlc).sum())
        valid_expected_timestamps = pd.DatetimeIndex(
            timestamps[valid_ohlc].drop_duplicates()
        ).intersection(expected)
        delta_valid = int(dataset["delta_source_valid"].sum())
        delta_invalid = int((~dataset["delta_source_valid"]).sum())
        oi_matched = int(dataset["oi"].notna().sum())
        oi_missing = int(dataset["oi"].isna().sum())
        oi_stale = int(dataset["oi_alignment_quality"].eq("STALE").sum())
        future_matches = int(dataset["future_oi_match"].sum())
        ages = dataset["oi_age_seconds"].dropna()
        ordered = pd.Series(unique_timestamps.sort_values())
        gaps = int(ordered.diff().gt(BAR_INTERVAL).sum()) if len(ordered) else 0
        segments = gaps + 1 if len(ordered) else 0
        requested = len(expected)
        kline_coverage = (
            len(valid_expected_timestamps) / requested if requested else 0.0
        )
        oi_coverage = oi_matched / len(dataset) if len(dataset) else 0.0

        warnings: list[str] = []
        critical = []
        if duplicate_klines:
            critical.append("Unresolved duplicate kline timestamps")
        if invalid_ohlc:
            critical.append("Invalid OHLC rows")
        if off_grid:
            critical.append("Klines outside the requested five-minute grid")
        if delta_invalid:
            critical.append("Invalid taker-volume Delta source rows")
        if future_matches:
            critical.append("Future Open Interest alignment detected")
        if kline_coverage < request.minimum_usable_kline_coverage:
            critical.append("Kline coverage is below the usable minimum")
        if oi_coverage < request.minimum_usable_oi_coverage:
            critical.append("Open Interest coverage is below the usable minimum")
        if len(dataset) and (pd.isna(dataset.iloc[0]["oi"]) or pd.isna(dataset.iloc[-1]["oi"])):
            critical.append("Open Interest does not cover the requested boundaries")

        if critical:
            status = DatasetStatus.INVALID
            warnings.extend(critical)
        else:
            if kline_coverage < request.research_kline_coverage:
                warnings.append("Kline coverage is below the 99.9% research default")
            if oi_coverage < request.research_oi_coverage:
                warnings.append("Open Interest coverage is below the 99% research default")
            if missing_klines:
                warnings.append("Requested kline grid contains missing bars")
            if oi_missing:
                warnings.append("Some bars have explicit missing Open Interest")
            if oi_stale:
                warnings.append("Some bars use stale but permitted Open Interest")
            if missing_kline_dates:
                warnings.append("Some official kline archive dates were unavailable")
            if missing_oi_dates:
                warnings.append("Some official Open Interest archive dates were unavailable")
            status = (
                DatasetStatus.USABLE_WITH_WARNINGS
                if warnings
                else DatasetStatus.VALID
            )

        return BuilderQualityReport(
            requested_bars=requested,
            received_klines=len(dataset),
            missing_klines=missing_klines,
            duplicate_klines=duplicate_klines,
            invalid_ohlc_rows=invalid_ohlc,
            off_grid_klines=off_grid,
            delta_valid_rows=delta_valid,
            delta_invalid_rows=delta_invalid,
            oi_source_rows=len(oi_source),
            oi_matched_rows=oi_matched,
            oi_missing_rows=oi_missing,
            oi_stale_rows=oi_stale,
            oi_coverage=oi_coverage,
            kline_coverage=kline_coverage,
            maximum_oi_age=float(ages.max()) if not ages.empty else None,
            median_oi_age=float(ages.median()) if not ages.empty else None,
            future_oi_matches=future_matches,
            detected_gaps=gaps,
            segments=segments,
            available_kline_start=(
                str(timestamps.min()) if not timestamps.empty else None
            ),
            available_kline_end=(
                str(timestamps.max()) if not timestamps.empty else None
            ),
            available_oi_start=(
                str(oi_source["oi_source_timestamp"].min())
                if not oi_source.empty
                else None
            ),
            available_oi_end=(
                str(oi_source["oi_source_timestamp"].max())
                if not oi_source.empty
                else None
            ),
            missing_kline_source_dates=missing_kline_dates,
            missing_oi_source_dates=missing_oi_dates,
            status=status,
            warnings=warnings,
        )
