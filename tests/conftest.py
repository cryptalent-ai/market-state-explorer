from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data_io import prepare_market_data
from src.features import build_derived_features


def fixed_market_frame(n=420):
    i = np.arange(n)
    opened = 60000 + i * 2 + ((i * 37) % 101) - 50
    body = ((i * 19) % 73) - 36
    closed = opened + body
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC"),
        "open": opened.astype(float), "close": closed.astype(float),
        "high": np.maximum(opened, closed) + 5 + (i % 11),
        "low": np.minimum(opened, closed) - 5 - (i % 13),
        "volume": 10.0 + ((i * 43) % 109),
        "delta": (((i * 29) % 61) - 30) / 3,
        "oi": 100000.0 + i * 3 + ((i * 17) % 53),
    })


@pytest.fixture
def derived():
    return build_derived_features(prepare_market_data(fixed_market_frame()).frame)


@pytest.fixture(params=["relay", "archive"])
def hosted_frame(derived, request):
    frame = derived.tail(40).copy()
    if request.param == "relay":
        from src.relay import RELAY_COLUMNS
        frame = frame[[c for c in RELAY_COLUMNS if c in frame]]
    for column in frame.select_dtypes(include="number"):
        frame[column] = frame[column].astype(str)
    for column in ("lehr_short_pressure", "lehr_long_pressure", "helr_event", "near_state_boundary"):
        frame[column] = frame[column].astype(str)
    frame["timestamp"] = frame["timestamp"].astype(str)
    frame["oi_log_change"] = ""
    return frame
