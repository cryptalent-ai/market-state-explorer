from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.live_data import build_recent_market_data, completed_bar_boundary
from src.providers.base import MarketDataProvider, SourceBatch


class FakeProvider(MarketDataProvider):
    def __init__(self) -> None:
        opens = pd.to_datetime(
            [
                "2026-10-05 11:50:00+00:00",
                "2026-10-05 11:55:00+00:00",
                "2026-10-05 12:00:00+00:00",
                "2026-10-05 12:05:00+00:00",
            ]
        )
        self.klines = pd.DataFrame(
            {
                "timestamp": opens,
                "bar_close_timestamp": opens + pd.Timedelta(minutes=5),
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [102.0, 103.0, 104.0, 105.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [101.0, 102.0, 103.0, 104.0],
                "volume": [10.0, 11.0, 12.0, 13.0],
                "taker_buy_base_volume": [6.0, 7.0, 8.0, 9.0],
            }
        )
        closes = opens + pd.Timedelta(minutes=5)
        self.oi = pd.DataFrame(
            {
                "oi_source_timestamp": closes,
                "oi": [1000.0, 1001.0, 1002.0, 1003.0],
            }
        )

    def fetch_klines(self, start, end, progress=None):  # noqa: ANN001
        return SourceBatch(data=self.klines.copy(), source_urls=["kline-test"])

    def fetch_open_interest(self, start, end, progress=None):  # noqa: ANN001
        return SourceBatch(data=self.oi.copy(), source_urls=["oi-test"])

    def source_metadata(self):
        return {"source": "fake"}


def test_completed_bar_boundary_has_safety_lag() -> None:
    now = datetime(2026, 10, 5, 12, 5, 5, tzinfo=timezone.utc)
    assert completed_bar_boundary(now) == pd.Timestamp("2026-10-05 12:00:00+00:00")


def test_recent_data_excludes_open_bar_and_future_oi(tmp_path: Path) -> None:
    market, metadata = build_recent_market_data(
        cache_root=tmp_path,
        history_days=2,
        now=datetime(2026, 10, 5, 12, 7, 0, tzinfo=timezone.utc),
        provider=FakeProvider(),
    )
    assert len(market.frame) == 3
    assert market.frame["bar_close_timestamp"].max() == pd.Timestamp(
        "2026-10-05 12:05:00+00:00"
    )
    assert metadata.future_oi_matches == 0
    assert metadata.oi_coverage == 1.0
    assert metadata.completed_through_utc.startswith("2026-10-05 12:05:00")
