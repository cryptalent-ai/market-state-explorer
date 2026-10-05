"""Source-routing contracts remain the existing implementations, not UI copies."""
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest

from src.config import ModelConfig
from src.providers.base import InvalidSourceResponse
from tests.conftest import fixed_market_frame
from tests.test_live_data import FakeProvider


@pytest.mark.parametrize("mode", ["Auto (Relay → Archive)", "Near-Real-Time Relay"])
def test_fresh_relay_has_priority(monkeypatch, derived, mode):
    import src.web_app as sources
    from src.web_app_v13 import _load_selected_dataset
    assert _load_selected_dataset is sources._load_selected_dataset
    meta = SimpleNamespace(fresh=True, age_seconds=60)
    monkeypatch.setattr(sources, "load_relay_dataset", lambda: (derived, meta))
    monkeypatch.setattr(sources, "load_binance_dataset", lambda *a: pytest.fail("Fresh relay must not request archive"))
    result = _load_selected_dataset(mode, None, ModelConfig())
    assert result[0] is derived
    assert result[2] is meta
    assert result[3] is None


@pytest.mark.parametrize("mode", ["Auto (Relay → Archive)", "Near-Real-Time Relay"])
def test_stale_relay_never_becomes_current(monkeypatch, derived, mode):
    import src.web_app as sources
    stale = SimpleNamespace(fresh=False, age_seconds=901)
    archive = SimpleNamespace(source="Official Binance delayed hosted fallback")
    monkeypatch.setattr(sources, "load_relay_dataset", lambda: (derived, stale))
    monkeypatch.setattr(sources, "load_binance_dataset", lambda *a: (derived, None, archive))
    result = sources._load_selected_dataset(mode, None, ModelConfig())
    assert "stale" in result[3]
    if mode.startswith("Auto"):
        assert result[2] is archive
        assert "delayed" in result[4]
    else:
        assert result[0] is None and result[2] is None


def test_source_upload_calls_audited_pipeline():
    from src.web_app_v13 import _load_selected_dataset
    result = _load_selected_dataset("Upload CSV", BytesIO(fixed_market_frame().to_csv(index=False).encode()), ModelConfig())
    assert result[0] is not None and result[3] is None
    assert result[4] == "Uploaded research CSV"
    assert result[1].usable_state_rows > 0


def test_http451_uses_official_delayed_fallback(monkeypatch, tmp_path):
    import src.live_data as sources
    class BlockedProvider:
        def __init__(self, *a, **kw):
            pass
        def fetch_klines(self, *a):
            raise InvalidSourceResponse("HTTP 451 restricted location")
    marker = object()
    calls = []
    monkeypatch.setattr(sources, "BinanceUSDMProvider", BlockedProvider)
    monkeypatch.setattr(sources, "build_archive_fallback_market_data", lambda **kw: (calls.append(kw) or marker))
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    assert sources.build_recent_market_data(cache_root=tmp_path, now=now) is marker
    assert len(calls) == 1 and calls[0]["now"] == pd.Timestamp(now)


def test_custom_provider_451_is_not_silently_replaced(monkeypatch, tmp_path):
    import src.live_data as sources
    class Blocked(FakeProvider):
        def fetch_klines(self, *a):
            raise InvalidSourceResponse("HTTP 451 restricted location")
    monkeypatch.setattr(sources, "build_archive_fallback_market_data", lambda **kw: pytest.fail("Must not substitute a custom provider"))
    with pytest.raises(InvalidSourceResponse):
        sources.build_recent_market_data(cache_root=tmp_path, provider=Blocked())


def test_archive_lag_next_day_oi_and_future_exclusion(monkeypatch, tmp_path):
    import src.live_data as sources
    requests = []
    class OfficialArchive(FakeProvider):
        def __init__(self, *a, **kw):
            super().__init__()
            self.klines["timestamp"] = pd.date_range("2026-10-02 23:45", periods=4, freq="5min", tz="UTC")
            self.klines["bar_close_timestamp"] = self.klines.timestamp + pd.Timedelta(minutes=5)
            self.oi["oi_source_timestamp"] = self.klines.bar_close_timestamp
        def fetch_klines(self, start, end, progress=None):
            requests.append(("klines", start, end))
            return super().fetch_klines(start, end)
        def fetch_open_interest(self, start, end, progress=None):
            requests.append(("oi", start, end))
            return super().fetch_open_interest(start, end)
    monkeypatch.setattr(sources, "BinanceUSDMProvider", OfficialArchive)
    market, meta = sources.build_archive_fallback_market_data(cache_root=tmp_path, history_days=2, now=datetime(2026, 10, 5, 12, tzinfo=timezone.utc))
    assert meta.requested_end == "2026-10-02"
    assert str(requests[1][2]) == "2026-10-03"
    assert len(market.frame) == 3
    assert market.frame.bar_close_timestamp.max() == pd.Timestamp("2026-10-03 00:00Z")
    assert meta.future_oi_matches == 0
    assert "delayed hosted fallback" in meta.source
