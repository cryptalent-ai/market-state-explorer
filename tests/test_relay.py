from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.relay import RELAY_COLUMNS, build_relay_comment, parse_relay_comment


def _frame(rows: int = 40) -> pd.DataFrame:
    index = pd.RangeIndex(rows)
    data: dict[str, object] = {}
    for column in RELAY_COLUMNS:
        if column == "timestamp":
            data[column] = pd.date_range("2026-10-05 00:00:00+00:00", periods=rows, freq="5min")
        elif column in {"positioning_state", "effort_result_region", "data_quality_flag"}:
            value = {
                "positioning_state": "Mixed / Low Conviction",
                "effort_result_region": "High Effort / High Result",
                "data_quality_flag": "",
            }[column]
            data[column] = [value] * rows
        elif column in {"lehr_short_pressure", "lehr_long_pressure", "helr_event", "near_state_boundary"}:
            data[column] = [False] * rows
        elif column == "bar_direction":
            data[column] = [1 if i % 2 == 0 else -1 for i in index]
        else:
            data[column] = [float(i + 1) for i in index]
    return pd.DataFrame(data)


def test_relay_round_trip_is_fresh() -> None:
    now = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
    body = build_relay_comment(
        _frame(),
        source="test",
        completed_through_utc="2026-10-05 03:55:00+00:00",
        oi_coverage=1.0,
        future_oi_matches=0,
        updated_at=now,
    )
    decoded, metadata = parse_relay_comment(body, now=now + timedelta(minutes=5))
    assert len(decoded) == 40
    assert metadata.fresh is True
    assert metadata.age_seconds == 300
    assert metadata.future_oi_matches == 0
    assert decoded["timestamp"].dt.tz is not None


def test_relay_becomes_stale_after_fifteen_minutes() -> None:
    now = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
    body = build_relay_comment(
        _frame(),
        source="test",
        completed_through_utc="2026-10-05 03:55:00+00:00",
        oi_coverage=1.0,
        future_oi_matches=0,
        updated_at=now,
    )
    _, metadata = parse_relay_comment(body, now=now + timedelta(minutes=16))
    assert metadata.fresh is False


def test_relay_rejects_future_oi_matches() -> None:
    now = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
    body = build_relay_comment(
        _frame(),
        source="test",
        completed_through_utc="2026-10-05 03:55:00+00:00",
        oi_coverage=1.0,
        future_oi_matches=1,
        updated_at=now,
    )
    with pytest.raises(ValueError, match="future OI"):
        parse_relay_comment(body, now=now)
