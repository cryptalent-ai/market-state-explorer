"""Freshness/cache hotfix contracts; real provider and publisher, no network writes."""
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from src.config import ModelConfig
from src.providers.base import SourceUnavailable
from src.providers.binance_usdm import BinanceUSDMProvider, KLINE_REST_URL
from src.cache import RawDataCache
from src.relay import RELAY_MARKER, RELAY_FRESH_SECONDS, build_relay_comment, parse_relay_comment
from tests.test_relay import _frame


class GrowingOfficialHttp:
    """Official-shaped string numerics, an open candle and future OI included."""
    def __init__(self, clock="2026-10-05 12:07:30Z"):
        self.clock = pd.Timestamp(clock)
        self.archive_days = set()
        self.json_calls = []
        self.byte_calls = []

    def records(self, start, end, klines, *, archive=False):
        upper = end if archive else min(end, self.clock.floor("5min") if klines else self.clock.ceil("5min"))
        result = []
        for ts in pd.date_range(start, upper, freq="5min"):
            tick = int(ts.timestamp() // 300)
            price = 60000 + tick % 71
            volume = 10 + tick % 19
            if klines:
                result.append([int(ts.timestamp()*1000), str(price), str(price+3), str(price-3), str(price+(tick % 3)-1), str(volume), int((ts+pd.Timedelta(minutes=5)).timestamp()*1000)-1, str(price*volume), 10, str(volume*(0.4 if tick % 2 else 0.6)), str(price*volume/2), "0"])
            else:
                result.append({"timestamp": int(ts.timestamp()*1000), "symbol": "BTCUSDT", "sumOpenInterest": str(100000+tick % 103), "sumOpenInterestValue": str(price*100000)})
        return result

    def get_json(self, url, *, params):
        self.json_calls.append((url, dict(params)))
        start = pd.Timestamp(params["startTime"], unit="ms", tz="UTC")
        end = pd.Timestamp(params["endTime"], unit="ms", tz="UTC").floor("5min")
        return self.records(start, end, url == KLINE_REST_URL)[:params["limit"]]

    def get_bytes(self, url):
        self.byte_calls.append(url)
        day = pd.Timestamp(re.search(r"(\d{4}-\d{2}-\d{2})", url)[1], tz="UTC")
        if day.date() not in self.archive_days:
            raise SourceUnavailable("Official archive not published yet")
        klines = "/klines/" in url
        records = self.records(day, day+pd.Timedelta(hours=23, minutes=55), klines, archive=True)
        if klines:
            csv = "\n".join(",".join(map(str, row)) for row in records)
        else:
            csv = "create_time,symbol,sum_open_interest,sum_open_interest_value\n" + "\n".join(f"{pd.Timestamp(row['timestamp'], unit='ms', tz='UTC')},BTCUSDT,{row['sumOpenInterest']},{row['sumOpenInterestValue']}" for row in records)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            info = zipfile.ZipInfo("official.csv")  # stable checksum across requests
            archive.writestr(info, csv)
        payload = buffer.getvalue()
        return sha256(payload).hexdigest().encode() if url.endswith(".CHECKSUM") else payload


def provider(tmp_path, http):
    return BinanceUSDMProvider(tmp_path, http=http, now=lambda: http.clock.to_pydatetime())


@pytest.mark.parametrize("method,column", [("fetch_klines", "timestamp"), ("fetch_open_interest", "oi_source_timestamp")])
def test_current_day_rest_refreshes_same_files(tmp_path, method, column):
    http = GrowingOfficialHttp()
    day = http.clock.date()
    first = getattr(provider(tmp_path, http), method)(day, day)
    paths = set(tmp_path.rglob("*"))
    http.clock += pd.Timedelta(minutes=5)
    second = getattr(provider(tmp_path, http), method)(day, day)
    assert second.data[column].max() > first.data[column].max()
    assert first.downloads == second.downloads == 1
    assert second.cache_hits == 0
    assert set(tmp_path.rglob("*")) == paths
    assert not list(tmp_path.rglob("*.part-*"))


@pytest.mark.parametrize("method,column", [("fetch_klines", "timestamp"), ("fetch_open_interest", "oi_source_timestamp")])
def test_previous_day_partial_rest_refreshes_without_archive(tmp_path, method, column):
    http = GrowingOfficialHttp()
    day = http.clock.date()
    first = getattr(provider(tmp_path, http), method)(day, day)
    http.clock = pd.Timestamp("2026-10-06 00:07:30Z")
    second = getattr(provider(tmp_path, http), method)(day, day)
    assert second.data[column].max() == pd.Timestamp("2026-10-05 23:55Z")
    assert len(second.data) > len(first.data)
    assert second.downloads == 1 and second.cache_hits == 0


@pytest.mark.parametrize("method", ["fetch_klines", "fetch_open_interest"])
@pytest.mark.parametrize("archive_available", [True, False])
def test_completed_historical_day_is_immutable(tmp_path, method, archive_available):
    http = GrowingOfficialHttp()
    day = http.clock.date() - timedelta(days=3)
    if archive_available:
        http.archive_days.add(day)
    first = getattr(provider(tmp_path, http), method)(day, day)
    json_count, byte_count = len(http.json_calls), len(http.byte_calls)
    second = getattr(provider(tmp_path, http), method)(day, day)
    pd.testing.assert_frame_equal(first.data, second.data, check_exact=True)
    assert second.cache_hits == 1 and second.downloads == 0
    assert len(http.json_calls) == json_count
    if archive_available:
        assert len(http.byte_calls) == byte_count


@pytest.mark.parametrize("method", ["fetch_klines", "fetch_open_interest"])
def test_archive_takes_priority_over_partial_rest(tmp_path, method):
    http = GrowingOfficialHttp()
    day = http.clock.date()
    first = getattr(provider(tmp_path, http), method)(day, day)
    http.clock += pd.Timedelta(days=1)
    http.archive_days.add(day)
    second = getattr(provider(tmp_path, http), method)(day, day)
    assert len(second.data) > len(first.data)
    assert all("data.binance.vision" in url for url in second.source_urls)
    third = getattr(provider(tmp_path, http), method)(day, day)
    assert third.cache_hits == 1


def test_refresh_day_uses_utc_not_local_calendar(tmp_path):
    http = GrowingOfficialHttp("2026-10-06 00:07:30+08:00")
    source = provider(tmp_path, http)
    assert source._refresh_rest_day(pd.Timestamp("2026-10-04").date())
    assert not source._refresh_rest_day(pd.Timestamp("2026-10-03").date())


def cache_entry(cache, payload=b"[1]", **kwargs):
    return cache.ensure_generated_payload(relative_directory=Path("BTCUSDT"), filename="active.json", source_url="official-rest", fetch=lambda: payload, validate=json.loads, **kwargs)


@pytest.mark.parametrize("failure", ["fetch", "validation", "stage", "replace"])
def test_failed_refresh_preserves_good_pair_and_cleans_temporary_files(tmp_path, monkeypatch, failure):
    cache = RawDataCache(tmp_path)
    original = cache_entry(cache)
    snapshot = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    if failure == "fetch":
        def fetch():
            raise OSError("fetch failed")
        kwargs = {"fetch": fetch, "validate": json.loads}
    else:
        kwargs = {"fetch": lambda: b"bad" if failure == "validation" else b"[2]", "validate": json.loads}
    if failure == "stage":
        real_stage = RawDataCache._stage_payload
        def stage(path, payload):
            if path.name.endswith("sha256"):
                raise OSError("stage failed")
            return real_stage(path, payload)
        monkeypatch.setattr(RawDataCache, "_stage_payload", staticmethod(stage))
    if failure == "replace":
        real_replace = Path.replace
        def replace(path, target):
            if str(target).endswith("sha256"):
                raise OSError("replace failed")
            return real_replace(path, target)
        monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises((OSError, ValueError)):
        cache.ensure_generated_payload(relative_directory=Path("BTCUSDT"), filename="active.json", source_url="official-rest", refresh_existing=True, **kwargs)
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == snapshot
    assert original.path.read_bytes() == b"[1]"


def test_successful_atomic_refresh_reuses_paths(tmp_path):
    cache = RawDataCache(tmp_path)
    old = cache_entry(cache)
    new = cache_entry(cache, b"[2]", refresh_existing=True)
    assert new.path == old.path and new.payload == b"[2]" and not new.from_cache
    assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 2
    assert cache_entry(cache).payload == b"[2]"


def relay_body(completed="2026-10-05 12:05Z", publication="2026-10-05 12:07Z"):
    return build_relay_comment(_frame(), source="official", completed_through_utc=completed, oi_coverage=1, future_oi_matches=0, updated_at=pd.Timestamp(publication))


@pytest.mark.parametrize("publication,completed,expected", [("12:07", "12:05", True), ("12:07", "07:05", False), ("11:50", "12:05", False), ("11:52", "11:52", True), ("12:07", "11:51:59", False)])
def test_publication_and_market_data_freshness_are_independent(publication, completed, expected):
    _, meta = parse_relay_comment(relay_body(f"2026-10-05 {completed}Z", f"2026-10-05 {publication}Z"), now=pd.Timestamp("2026-10-05 12:07Z"))
    assert RELAY_FRESH_SECONDS == 900
    assert meta.fresh is expected
    assert meta.fresh == (meta.publication_fresh and meta.market_data_fresh)
    assert meta.age_seconds >= 0 and meta.market_data_age_seconds >= 0


@pytest.mark.parametrize("completed", [None, "", "not-a-date", "NaT", 123, "2026-10-05 12:10Z", "missing"])
def test_bad_completed_through_is_rejected(completed):
    body = relay_body()
    envelope = json.loads(re.search(r"```json\s*(\{.*\})\s*```", body, re.DOTALL)[1])
    if completed == "missing":
        envelope.pop("completed_through_utc")
    else:
        envelope["completed_through_utc"] = completed
    with pytest.raises(ValueError, match="completed-through"):
        parse_relay_comment(RELAY_MARKER+"\n```json\n"+json.dumps(envelope)+"\n```", now=pd.Timestamp("2026-10-05 12:07Z"))


@pytest.mark.parametrize("completed", ["2026-10-05 12:05", "2026-10-05 20:05+08:00"])
def test_completed_boundary_not_last_bar_open_is_used(completed):
    frame = _frame()
    frame["timestamp"] = pd.date_range(end="2026-10-05 12:00Z", periods=len(frame), freq="5min")
    body = build_relay_comment(frame, source="official", completed_through_utc=completed, oi_coverage=1, future_oi_matches=0, updated_at=pd.Timestamp("2026-10-05 12:16Z"))
    _, meta = parse_relay_comment(body, now=pd.Timestamp("2026-10-05 12:16Z"))
    assert meta.fresh and meta.market_data_age_seconds == 660  # open timestamp age would be 960


@pytest.mark.parametrize("mode", ["Auto (Relay → Archive)", "Near-Real-Time Relay"])
def test_stale_market_fresh_publication_never_becomes_active(monkeypatch, derived, mode):
    import src.web_app as sources
    _, meta = parse_relay_comment(relay_body("2026-10-05 07:05Z"), now=pd.Timestamp("2026-10-05 12:07Z"))
    assert meta.publication_fresh and not meta.fresh
    archive = SimpleNamespace(source="Official Binance delayed hosted fallback")
    monkeypatch.setattr(sources, "load_relay_dataset", lambda: (derived, meta))
    monkeypatch.setattr(sources, "load_binance_dataset", lambda *a: (derived, None, archive))
    result = sources._load_selected_dataset(mode, None, ModelConfig())
    assert "stale" in result[3]
    assert result[2] is archive if mode.startswith("Auto") else result[0] is None


@pytest.mark.parametrize("completed", ["2026-10-05 07:05Z", "invalid", "2026-10-05 12:10Z"])
def test_publisher_rejects_bad_source_without_comment_write(tmp_path, monkeypatch, capsys, completed):
    import scripts.publish_live_relay as publisher
    monkeypatch.setattr(publisher, "_utc_now", lambda: pd.Timestamp("2026-10-05 12:07Z"))
    monkeypatch.setattr(publisher, "build_recent_market_data", lambda **kw: (None, SimpleNamespace(source="official", completed_through_utc=completed)))
    monkeypatch.setattr(publisher, "_publish_with_gh", lambda body: pytest.fail("Must preserve previous good comment"))
    assert publisher.run_cli(["--cache-root", str(tmp_path)]) == 1
    assert "Relay publish failed:" in capsys.readouterr().err


def test_publisher_rechecks_age_after_feature_work(tmp_path, monkeypatch, capsys, derived):
    import scripts.publish_live_relay as publisher
    clock = iter(map(pd.Timestamp, ["2026-10-05 12:00Z", "2026-10-05 12:00Z", "2026-10-05 12:15Z", "2026-10-05 12:15:01Z"]))
    monkeypatch.setattr(publisher, "_utc_now", lambda: next(clock))
    meta = SimpleNamespace(source="official", completed_through_utc="2026-10-05 12:00Z", oi_coverage=1, future_oi_matches=0)
    monkeypatch.setattr(publisher, "build_recent_market_data", lambda **kw: (SimpleNamespace(frame=derived), meta))
    monkeypatch.setattr(publisher, "build_derived_features", lambda *a: derived)
    monkeypatch.setattr(publisher, "_publish_with_gh", lambda body: pytest.fail("Aging payload must not overwrite comment"))
    assert publisher.run_cli(["--cache-root", str(tmp_path)]) == 1
    assert "market data is stale" in capsys.readouterr().err


def test_backward_oi_alignment_never_selects_closer_future_observation():
    from src.oi_alignment import align_open_interest
    closes = pd.to_datetime(["2026-10-05 12:00Z", "2026-10-05 12:05Z", "2026-10-05 12:10Z"])
    bars = pd.DataFrame({"timestamp": closes-pd.Timedelta(minutes=5), "bar_close_timestamp": closes})
    observations = pd.DataFrame({"oi_source_timestamp": pd.to_datetime(["2026-10-05 11:59:00Z", "2026-10-05 12:00:01Z", "2026-10-05 12:05:01Z", "2026-10-05 12:10:01Z"]), "oi": [100., 999., 888., 777.]})
    aligned = align_open_interest(bars, observations)
    assert aligned.oi.tolist() == [100., 999., 888.]
    assert aligned.oi_age_seconds.tolist() == [60., 299., 299.]
    assert aligned.future_oi_match.sum() == 0
    assert (aligned.oi_source_timestamp <= aligned.bar_close_timestamp).all()


def test_publisher_delayed_archive_defense_still_rejects(tmp_path, monkeypatch, capsys):
    import scripts.publish_live_relay as publisher
    monkeypatch.setattr(publisher, "build_recent_market_data", lambda **kw: (None, SimpleNamespace(source="Official Binance delayed hosted fallback")))
    monkeypatch.setattr(publisher, "_publish_with_gh", lambda body: pytest.fail("Delayed archive cannot be published as live"))
    assert publisher.run_cli(["--cache-root", str(tmp_path)]) == 1
    assert "HTTP 451" in capsys.readouterr().err


@pytest.mark.parametrize("dry_run", [True, False])
def test_two_publisher_runs_five_minutes_apart_advance_completed_bar(tmp_path, monkeypatch, capsys, dry_run):
    import scripts.publish_live_relay as publisher
    import src.live_data as live
    http = GrowingOfficialHttp()
    factory = lambda cache_root, **kw: provider(cache_root, http)
    monkeypatch.setattr(live, "BinanceUSDMProvider", factory)
    monkeypatch.setattr(publisher, "_utc_now", lambda: http.clock)
    bodies = []
    monkeypatch.setattr(publisher, "_publish_with_gh", bodies.append)
    args = ["--cache-root", str(tmp_path)] + (["--dry-run"] if dry_run else [])
    audits = []
    markets = []
    original_builder = publisher.build_recent_market_data
    def build(**kwargs):
        market, meta = original_builder(**kwargs)
        markets.append(market.frame.copy())
        return market, meta
    monkeypatch.setattr(publisher, "build_recent_market_data", build)
    for _ in range(2):
        assert publisher.run_cli(args) == 0
        audits.append(json.loads(capsys.readouterr().out.splitlines()[0]))
        http.clock += pd.Timedelta(minutes=5)
    assert pd.Timestamp(audits[1]["publication_timestamp"])-pd.Timestamp(audits[0]["publication_timestamp"]) == pd.Timedelta(minutes=5)
    assert pd.Timestamp(audits[0]["completed_through_timestamp"]) == pd.Timestamp("2026-10-05 12:05Z")
    assert pd.Timestamp(audits[1]["completed_through_timestamp"]) == pd.Timestamp("2026-10-05 12:10Z")
    assert pd.Timestamp(audits[1]["latest_state_timestamp"]) == pd.Timestamp("2026-10-05 12:05Z")
    assert audits[1]["market_rows"] == audits[0]["market_rows"]+1
    assert audits[0]["downloads"] == 16
    assert audits[1]["cache_hits"] == 12 and audits[1]["downloads"] == 4
    for audit, market in zip(audits, markets):
        assert audit["market_data_age_seconds"] == 150
        assert audit["future_oi_matches"] == 0 and audit["oi_coverage"] == 1
        assert market.bar_close_timestamp.max() == pd.Timestamp(audit["completed_through_timestamp"])
        assert (market.oi_source_timestamp <= market.bar_close_timestamp).all()
        assert market.timestamp.max() < pd.Timestamp(audit["completed_through_timestamp"])
    pd.testing.assert_frame_equal(markets[0], markets[1].iloc[:len(markets[0])], check_exact=True)
    assert len(bodies) == (0 if dry_run else 2)
    for body, audit in zip(bodies, audits):
        _, meta = parse_relay_comment(body, now=pd.Timestamp(audit["publication_timestamp"]))
        assert meta.fresh
