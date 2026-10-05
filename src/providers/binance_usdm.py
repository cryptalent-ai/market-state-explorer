"""Official Binance USDⓈ-M BTCUSDT 5m historical provider."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
from typing import Any
import zipfile

import pandas as pd

from ..cache import RawDataCache
from ..http_client import ReliableHttpClient
from .base import (
    InvalidSourceResponse,
    MarketDataProvider,
    ProgressCallback,
    SourceBatch,
    SourceUnavailable,
)


ARCHIVE_BASE = "https://data.binance.vision/data/futures/um/daily"
REST_BASE = "https://fapi.binance.com"
KLINE_REST_URL = f"{REST_BASE}/fapi/v1/klines"
OI_REST_URL = f"{REST_BASE}/futures/data/openInterestHist"
OFFICIAL_DOCS_URL = (
    "https://developers.binance.com/en/docs/catalog/"
    "core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data"
)
OFFICIAL_ARCHIVE_DOCS_URL = "https://github.com/binance/binance-public-data"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
INTERVAL = pd.to_timedelta(5, unit="min")
REST_OI_RETENTION_DAYS = 31

KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)

ARCHIVE_KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)


def _utc_bounds(start: date, end: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_timestamp = pd.Timestamp(start, tz="UTC")
    end_exclusive = pd.Timestamp(end + timedelta(days=1), tz="UTC")
    return start_timestamp, end_exclusive


def _dates(start: date, end: date) -> Iterable[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def _archive_csv(payload: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = [
                name for name in archive.namelist() if name.lower().endswith(".csv")
            ]
            if len(members) != 1:
                raise InvalidSourceResponse(
                    "Official archive must contain exactly one CSV."
                )
            return archive.read(members[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as error:
        raise InvalidSourceResponse(
            "Official archive CSV could not be decoded."
        ) from error


def parse_kline_archive(payload: bytes) -> pd.DataFrame:
    """Parse the official archive kline schema, including headerless history."""

    text = _archive_csv(payload)
    first_token = text.split(",", 1)[0].strip().lower()
    if first_token == "open_time":
        raw = pd.read_csv(StringIO(text))
    else:
        raw = pd.read_csv(
            StringIO(text), header=None, names=ARCHIVE_KLINE_COLUMNS
        )
    raw = raw.rename(
        columns={
            "count": "trade_count",
            "taker_buy_volume": "taker_buy_base_volume",
        }
    )
    return _normalize_klines(raw)


def parse_kline_rest(records: list[list[Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=_kline_output_columns())
    if any(not isinstance(row, list) or len(row) != 12 for row in records):
        raise InvalidSourceResponse("Official kline REST response has invalid schema.")
    return _normalize_klines(pd.DataFrame(records, columns=KLINE_COLUMNS))


def _kline_output_columns() -> list[str]:
    return [
        "timestamp",
        "bar_close_timestamp",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base_volume",
        "quote_volume",
        "taker_buy_quote_volume",
        "trade_count",
    ]


def _normalize_klines(raw: pd.DataFrame) -> pd.DataFrame:
    required = set(KLINE_COLUMNS) - {"ignore"}
    missing = required - set(raw.columns)
    if missing:
        raise InvalidSourceResponse(
            "Official kline schema is missing: " + ", ".join(sorted(missing))
        )
    result = pd.DataFrame(index=raw.index)
    result["timestamp"] = pd.to_datetime(
        pd.to_numeric(raw["open_time"], errors="coerce"), unit="ms", utc=True
    )
    result["bar_close_timestamp"] = result["timestamp"] + INTERVAL
    result["close_time"] = pd.to_datetime(
        pd.to_numeric(raw["close_time"], errors="coerce"), unit="ms", utc=True
    )
    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base_volume",
        "quote_volume",
        "taker_buy_quote_volume",
    ):
        result[column] = pd.to_numeric(raw[column], errors="coerce")
    result["trade_count"] = pd.to_numeric(
        raw["trade_count"], errors="coerce"
    ).astype("Int64")
    if result[["timestamp", "bar_close_timestamp"]].isna().any().any():
        raise InvalidSourceResponse("Official kline timestamps are invalid.")
    return result.sort_values("timestamp", kind="stable").reset_index(drop=True)


def parse_metrics_archive(payload: bytes) -> pd.DataFrame:
    """Parse official five-minute metrics and select quantity, not value."""

    text = _archive_csv(payload)
    raw = pd.read_csv(StringIO(text))
    required = {"create_time", "symbol", "sum_open_interest"}
    missing = required - set(raw.columns)
    if missing:
        raise InvalidSourceResponse(
            "Official metrics schema is missing: " + ", ".join(sorted(missing))
        )
    result = pd.DataFrame(
        {
            "oi_source_timestamp": pd.to_datetime(
                raw["create_time"], utc=True, errors="coerce"
            ),
            "oi": pd.to_numeric(raw["sum_open_interest"], errors="coerce"),
            "oi_notional_audit": pd.to_numeric(
                raw.get("sum_open_interest_value"), errors="coerce"
            ),
            "symbol": raw["symbol"].astype("string"),
        }
    )
    return _validate_oi_frame(result)


def parse_metrics_rest(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=(
                "oi_source_timestamp",
                "oi",
                "oi_notional_audit",
                "symbol",
            )
        )
    try:
        result = pd.DataFrame(
            {
                "oi_source_timestamp": pd.to_datetime(
                    [row["timestamp"] for row in records], unit="ms", utc=True
                ),
                "oi": pd.to_numeric(
                    [row["sumOpenInterest"] for row in records], errors="coerce"
                ),
                "oi_notional_audit": pd.to_numeric(
                    [row.get("sumOpenInterestValue") for row in records],
                    errors="coerce",
                ),
                "symbol": pd.Series(
                    [row["symbol"] for row in records], dtype="string"
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidSourceResponse(
            "Official Open Interest REST response has invalid schema."
        ) from error
    return _validate_oi_frame(result)


def _validate_oi_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame["oi_source_timestamp"].isna().any() or frame["oi"].isna().any():
        raise InvalidSourceResponse("Official Open Interest rows contain invalid values.")
    if frame["oi"].le(0).any():
        raise InvalidSourceResponse("Official Open Interest quantity is not positive.")
    if frame["symbol"].ne(SYMBOL).any():
        raise InvalidSourceResponse("Official Open Interest archive symbol mismatch.")
    return frame.sort_values("oi_source_timestamp", kind="stable").reset_index(drop=True)


def _validate_json_list(payload: bytes) -> None:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidSourceResponse("Cached REST response is invalid JSON.") from error
    if not isinstance(value, list):
        raise InvalidSourceResponse("Cached REST response is not a list.")


class BinanceUSDMProvider(MarketDataProvider):
    """Fixed-scope official BTCUSDT USDⓈ-M 5m provider."""

    def __init__(
        self,
        cache_root: Path,
        *,
        http: ReliableHttpClient | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.cache = RawDataCache(cache_root)
        self.http = http or ReliableHttpClient()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _refresh_rest_day(self, day: date) -> bool:
        """Current/previous UTC dates may still have partial REST snapshots.

        Archive selection always happens first. Once an official archive is
        available, its immutable checksum cache remains the preferred source.
        """
        clock = pd.Timestamp(self.now())
        clock = clock.tz_localize("UTC") if clock.tzinfo is None else clock.tz_convert("UTC")
        return day >= clock.date() - timedelta(days=1)

    def fetch_klines(
        self,
        start: date,
        end: date,
        progress: ProgressCallback | None = None,
    ) -> SourceBatch:
        batch = SourceBatch(data=pd.DataFrame())
        frames: list[pd.DataFrame] = []
        for day in _dates(start, end):
            if progress:
                progress(f"Klines: {day.isoformat()}")
            archive_filename = f"{SYMBOL}-{TIMEFRAME}-{day.isoformat()}.zip"
            archive_url = (
                f"{ARCHIVE_BASE}/klines/{SYMBOL}/{TIMEFRAME}/{archive_filename}"
            )
            try:
                cached = self.cache.ensure_official_archive(
                    relative_directory=Path(SYMBOL) / "klines",
                    filename=archive_filename,
                    source_url=archive_url,
                    http=self.http,
                )
                frame = parse_kline_archive(cached.payload)
            except SourceUnavailable:
                frame, cached = self._rest_klines(day)
            frames.append(frame)
            batch.source_urls.append(cached.source_url)
            batch.cache_hits += int(cached.from_cache)
            batch.downloads += int(not cached.from_cache)
        batch.data = self._filter_klines(pd.concat(frames, ignore_index=True), start, end)
        return batch

    def fetch_open_interest(
        self,
        start: date,
        end: date,
        progress: ProgressCallback | None = None,
    ) -> SourceBatch:
        batch = SourceBatch(data=pd.DataFrame())
        frames: list[pd.DataFrame] = []
        retention_start = self.now().date() - timedelta(days=REST_OI_RETENTION_DAYS)
        for day in _dates(start, end):
            if progress:
                progress(f"Open Interest: {day.isoformat()}")
            filename = f"{SYMBOL}-metrics-{day.isoformat()}.zip"
            archive_url = f"{ARCHIVE_BASE}/metrics/{SYMBOL}/{filename}"
            try:
                cached = self.cache.ensure_official_archive(
                    relative_directory=Path(SYMBOL) / "open_interest",
                    filename=filename,
                    source_url=archive_url,
                    http=self.http,
                )
                frame = parse_metrics_archive(cached.payload)
            except SourceUnavailable:
                if day < retention_start:
                    batch.missing_dates.append(day)
                    continue
                try:
                    frame, cached = self._rest_open_interest(day)
                except SourceUnavailable:
                    batch.missing_dates.append(day)
                    continue
            frames.append(frame)
            batch.source_urls.append(cached.source_url)
            batch.cache_hits += int(cached.from_cache)
            batch.downloads += int(not cached.from_cache)
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            batch.data = self._filter_oi(combined, start, end)
        else:
            batch.data = pd.DataFrame(
                columns=(
                    "oi_source_timestamp",
                    "oi",
                    "oi_notional_audit",
                    "symbol",
                )
            )
        return batch

    def _rest_klines(self, day: date):
        filename = f"{SYMBOL}-{TIMEFRAME}-{day.isoformat()}-REST.json"
        start, end_exclusive = _utc_bounds(day, day)

        def fetch() -> bytes:
            records: list[list[Any]] = []
            cursor = int(start.timestamp() * 1000)
            final = int(end_exclusive.timestamp() * 1000) - 1
            while cursor <= final:
                page = self.http.get_json(
                    KLINE_REST_URL,
                    params={
                        "symbol": SYMBOL,
                        "interval": TIMEFRAME,
                        "startTime": cursor,
                        "endTime": final,
                        "limit": 1500,
                    },
                )
                if not isinstance(page, list):
                    raise InvalidSourceResponse("Kline REST response is not a list.")
                if not page:
                    break
                records.extend(page)
                last_open = int(page[-1][0])
                next_cursor = last_open + int(INTERVAL.total_seconds() * 1000)
                if next_cursor <= cursor:
                    raise InvalidSourceResponse("Kline REST pagination did not advance.")
                cursor = next_cursor
                if len(page) < 1500:
                    break
            return json.dumps(records, separators=(",", ":")).encode("utf-8")

        cached = self.cache.ensure_generated_payload(
            relative_directory=Path(SYMBOL) / "klines",
            filename=filename,
            source_url=KLINE_REST_URL,
            fetch=fetch,
            validate=lambda payload: (_validate_json_list(payload), parse_kline_rest(json.loads(payload))),
            refresh_existing=self._refresh_rest_day(day),
        )
        records = json.loads(cached.payload.decode("utf-8"))
        return parse_kline_rest(records), cached

    def _rest_open_interest(self, day: date):
        filename = f"{SYMBOL}-metrics-{day.isoformat()}-REST.json"
        start, end_exclusive = _utc_bounds(day, day)

        def fetch() -> bytes:
            records: list[dict[str, Any]] = []
            cursor = int(start.timestamp() * 1000)
            final = int(end_exclusive.timestamp() * 1000) - 1
            while cursor <= final:
                page = self.http.get_json(
                    OI_REST_URL,
                    params={
                        "symbol": SYMBOL,
                        "period": TIMEFRAME,
                        "startTime": cursor,
                        "endTime": final,
                        "limit": 500,
                    },
                )
                if not isinstance(page, list):
                    raise InvalidSourceResponse("OI REST response is not a list.")
                if not page:
                    break
                page = sorted(page, key=lambda row: int(row["timestamp"]))
                records.extend(page)
                next_cursor = int(page[-1]["timestamp"]) + 1
                if next_cursor <= cursor:
                    raise InvalidSourceResponse("OI REST pagination did not advance.")
                cursor = next_cursor
                if len(page) < 500:
                    break
            return json.dumps(records, separators=(",", ":")).encode("utf-8")

        cached = self.cache.ensure_generated_payload(
            relative_directory=Path(SYMBOL) / "open_interest",
            filename=filename,
            source_url=OI_REST_URL,
            fetch=fetch,
            validate=lambda payload: (_validate_json_list(payload), parse_metrics_rest(json.loads(payload))),
            refresh_existing=self._refresh_rest_day(day),
        )
        records = json.loads(cached.payload.decode("utf-8"))
        return parse_metrics_rest(records), cached

    @staticmethod
    def _filter_klines(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        lower, upper = _utc_bounds(start, end)
        return frame[
            frame["timestamp"].ge(lower) & frame["timestamp"].lt(upper)
        ].sort_values("timestamp", kind="stable").reset_index(drop=True)

    @staticmethod
    def _filter_oi(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        lower = pd.Timestamp(start, tz="UTC")
        upper = pd.Timestamp(end + timedelta(days=1), tz="UTC")
        return frame[
            frame["oi_source_timestamp"].ge(lower)
            & frame["oi_source_timestamp"].le(upper)
        ].sort_values("oi_source_timestamp", kind="stable").reset_index(drop=True)

    def source_metadata(self) -> dict[str, Any]:
        return {
            "provider": "Binance",
            "market": "USDT-M Perpetual",
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "archive_base": ARCHIVE_BASE,
            "kline_rest_endpoint": KLINE_REST_URL,
            "oi_rest_endpoint": OI_REST_URL,
            "official_documentation": OFFICIAL_DOCS_URL,
            "official_archive_documentation": OFFICIAL_ARCHIVE_DOCS_URL,
            "oi_field": "sum_open_interest / sumOpenInterest",
            "oi_value_field_excluded": (
                "sum_open_interest_value / sumOpenInterestValue"
            ),
            "oi_timestamp_semantics": "End time of the five-minute period",
            "oi_native_unit": "BTC base-asset quantity",
            "oi_output_unit": "BTC base-asset quantity",
            "oi_contract_multiplier": 1.0,
            "rest_oi_retention": "Official endpoint: latest one month only",
        }
