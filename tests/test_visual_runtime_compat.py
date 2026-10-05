from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from src.charts_v12 import state_map_figure, trajectory_figure


def _archive_like_frame(rows: int = 36) -> pd.DataFrame:
    idx = np.arange(rows, dtype=float)
    # Numeric columns intentionally use string/object values to mirror hosted/archive
    # dataframe coercion edge cases that synthetic float-only tests can miss.
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-10-01", periods=rows, freq="5min", tz="UTC").astype(str),
            "open": (100 + idx).astype(str),
            "high": (101 + idx).astype(str),
            "low": (99 + idx).astype(str),
            "close": (100.5 + idx).astype(str),
            "volume": (1000 + idx).astype(str),
            "delta": (np.sin(idx) * 100).astype(str),
            "delta_ratio": (np.sin(idx) / 10).astype(str),
            "oi": (5000 + idx).astype(str),
            "oi_log_change": np.where(idx % 7 == 0, "", "0.001"),
            "effort_score": np.sin(idx / 5.0).astype(str),
            "result_score": np.cos(idx / 6.0).astype(str),
            "state_strength": np.ones(rows).astype(str),
            "state_velocity": np.linspace(0, 1, rows).astype(str),
            "bar_direction": np.where(idx % 2 == 0, "1", "-1"),
            "positioning_state": np.where(idx % 2 == 0, "Short Covering", "Mixed / Low Conviction"),
            "effort_result_region": np.where(idx % 2 == 0, "High Effort / High Result", "Low Effort / Low Result"),
        }
    )


def test_v12_signatures_expose_new_controls() -> None:
    state_params = inspect.signature(state_map_figure).parameters
    trajectory_params = inspect.signature(trajectory_figure).parameters
    assert {"mode", "recent_points", "color_by"}.issubset(state_params)
    assert "view" in trajectory_params


def test_archive_like_object_dtypes_render_all_v12_views() -> None:
    frame = _archive_like_frame()
    figures = [
        state_map_figure(frame, mode="Density + recent", recent_points=20),
        state_map_figure(frame, mode="Recent only", recent_points=12),
        state_map_figure(frame, mode="Full scatter", color_by="Direction"),
        state_map_figure(frame, mode="Full scatter", color_by="Positioning"),
        trajectory_figure(frame, trail_length=12, view="2D trajectory"),
        trajectory_figure(frame, trail_length=12, view="Effort over time"),
        trajectory_figure(frame, trail_length=12, view="Result over time"),
        trajectory_figure(frame, trail_length=12, view="Strength / Velocity"),
    ]
    for figure in figures:
        figure.to_json()
