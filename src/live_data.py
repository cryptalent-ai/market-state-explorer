"""Free-host-safe recent Binance data acquisition for the public web app."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .data_io import MarketData, prepare_market_data
from .delta import reconstruct_delta
from .oi_alignment import align_open_interest
from .providers.base import InvalidSourceResponse, MarketDataProvider
from .providers.binance_usdm import BinanceUSDMProvider

BAR_INTERVAL = pd.Timedelta(minutes=5)
DEFAULT_HISTORY_DAYS = 8
DEFAULT_SAFETY_LAG_SECONDS = 15
ARCHIVE_FALLBACK_LAG_DAYS = 3


@dataclass(slots=True)
class LiveDataMetadata:
    """Small audit record for the recent-data path used by the public site."""

    source: str
    requested_start: str
    requested_end: str
    as_of_utc: str
    completed_through_utc: str
    rows: int
    oi_coverage: float
    missing_oi_rows: int
    stale_oi_rows: int
    future_oi_matches: int
    cache_hits: int
    downloads: int
    missing_kline_dates: list[str]
    missing_oi_dates: list[str]
    source_urls: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def completed_bar_boundary(
    now: datetime | pd.Timestamp | None = None,
    *,
    safety_lag_seconds: int = DEFAULT_SAFETY_LAG_SECONDS,
) -> pd.Timestamp:
    """Return the last five-minute UTC close boundary safe to treat as complete."""

    timestamp = pd.Timestamp(now or datetime.now(timezone.utc))
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    lagged = timestamp - pd.Timedelta(seconds=max(0, safety_lag_seconds))
    return lagged.floor(BAR_INTERVAL)


def _utc_clock(now: datetime | pd.Timestamp | None) -> pd.Timestamp:
    clock = pd.Timestamp(now or datetime.now(timezone.utc))
    if clock.tzinfo is None:
        return clock.tz_localize("UTC")
    return clock.tz_convert("UTC")


def _restricted_location_error(error: Exception) -> bool:
    text = str(error).lower()
    return "http 451" in text or "restricted location" in text


def _assemble_market_data(
    *,
    klines,
    oi,
    boundary: pd.Timestamp,
    clock: pd.Timestamp,
    start_date: date,
    end_date: date,
    source_label: str,
    max_oi_age_seconds: int,
) -> tuple[MarketData, LiveDataMetadata]:
    bars = klines.data.copy()
    if bars.empty:
        raise RuntimeError("Official Binance source returned no completed klines.")
    bars = bars[bars["bar_close_timestamp"].le(boundary)].copy()
    if bars.empty:
        raise RuntimeError("No completed five-minute bars are available yet.")

    oi_frame = oi.data.copy()
    if not oi_frame.empty:
        oi_frame = oi_frame[oi_frame["oi_source_timestamp"].le(boundary)].copy()

    with_delta = reconstruct_delta(bars)
    aligned = align_open_interest(
        with_delta,
        oi_frame,
        max_oi_age_seconds=max_oi_age_seconds,
    )
    aligned["open_time"] = aligned["timestamp"]
    aligned["symbol"] = "BTCUSDT"
    aligned["exchange"] = "Binance USDT-M"
    aligned["timeframe"] = "5m"

    market = prepare_market_data(aligned)
    oi_matched = int(market.frame["oi"].notna().sum())
    rows = len(market.frame)
    metadata = LiveDataMetadata(
        source=source_label,
        requested_start=start_date.isoformat(),
        requested_end=end_date.isoformat(),
        as_of_utc=clock.isoformat(),
        completed_through_utc=str(market.frame["bar_close_timestamp"].max()),
        rows=rows,
        oi_coverage=(oi_matched / rows if rows else 0.0),
        missing_oi_rows=int(market.frame["oi"].isna().sum()),
        stale_oi_rows=int(market.frame["oi_alignment_quality"].eq("STALE").sum()),
        future_oi_matches=int(market.frame["future_oi_match"].sum()),
        cache_hits=klines.cache_hits + oi.cache_hits,
        downloads=klines.downloads + oi.downloads,
        missing_kline_dates=[value.isoformat() for value in klines.missing_dates],
        missing_oi_dates=[value.isoformat() for value in oi.missing_dates],
        source_urls=list(dict.fromkeys(klines.source_urls + oi.source_urls)),
    )
    return market, metadata


def build_archive_fallback_market_data(
    *,
    cache_root: Path,
    history_days: int = DEFAULT_HISTORY_DAYS,
    now: datetime | pd.Timestamp | None = None,
    max_oi_age_seconds: int = 300,
) -> tuple[MarketData, LiveDataMetadata]:
    """Build the freshest archive-only window safe for geo-blocked cloud hosts.

    Binance's public daily archive is reachable from hosts where the futures REST
    API may return HTTP 451. The fallback deliberately ends three UTC days back so
    both the final kline archive and the next-day OI period-end archive have time
    to be published. It is therefore a delayed research snapshot, never labelled
    as real-time data.
    """

    if history_days < 2:
        raise ValueError("history_days must be at least 2")
    clock = _utc_clock(now)
    end_date = clock.date() - timedelta(days=ARCHIVE_FALLBACK_LAG_DAYS)
    start_date = end_date - timedelta(days=history_days - 1)
    boundary = pd.Timestamp(end_date + timedelta(days=1), tz="UTC")

    provider = BinanceUSDMProvider(
        cache_root,
        now=lambda: clock.to_pydatetime(),
    )
    klines = provider.fetch_klines(start_date, end_date)
    # Fetch the next UTC day as well so the final 23:55 candle can align to the
    # exact 00:00 period-end OI observation when that archive is available.
    oi = provider.fetch_open_interest(start_date, end_date + timedelta(days=1))
    return _assemble_market_data(
        klines=klines,
        oi=oi,
        boundary=boundary,
        clock=clock,
        start_date=start_date,
        end_date=end_date,
        source_label=(
            "Official Binance USDⓈ-M daily archive — delayed hosted fallback "
            "(futures REST unavailable from hosting region)"
        ),
        max_oi_age_seconds=max_oi_age_seconds,
    )


def build_recent_market_data(
    *,
    cache_root: Path,
    history_days: int = DEFAULT_HISTORY_DAYS,
    now: datetime | pd.Timestamp | None = None,
    provider: MarketDataProvider | None = None,
    max_oi_age_seconds: int = 300,
) -> tuple[MarketData, LiveDataMetadata]:
    """Acquire recent official BTCUSDT 5m data without ever using an open bar.

    When a cloud host receives Binance HTTP 451, the public web app falls back to
    Binance's official daily archives. That fallback is explicitly delayed and is
    never treated as a live/current market observation.
    """

    if history_days < 2:
        raise ValueError("history_days must be at least 2")
    boundary = completed_bar_boundary(now)
    end_date: date = boundary.date()
    start_date = end_date - timedelta(days=history_days - 1)
    clock = _utc_clock(now)

    active_provider = provider or BinanceUSDMProvider(
        cache_root,
        now=lambda: clock.to_pydatetime(),
    )
    try:
        klines = active_provider.fetch_klines(start_date, end_date)
        oi = active_provider.fetch_open_interest(start_date, end_date)
    except InvalidSourceResponse as error:
        # Only the default hosted Binance path may use the archive fallback.
        # Test/custom providers still surface their own source errors unchanged.
        if provider is not None or not _restricted_location_error(error):
            raise
        return build_archive_fallback_market_data(
            cache_root=cache_root,
            history_days=history_days,
            now=clock,
            max_oi_age_seconds=max_oi_age_seconds,
        )

    return _assemble_market_data(
        klines=klines,
        oi=oi,
        boundary=boundary,
        clock=clock,
        start_date=start_date,
        end_date=end_date,
        source_label="Official Binance USDⓈ-M public archive/REST",
        max_oi_age_seconds=max_oi_age_seconds,
    )
