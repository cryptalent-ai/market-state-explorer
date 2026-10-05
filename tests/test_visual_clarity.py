from __future__ import annotations

import numpy as np
import pandas as pd

from src.charts import state_map_figure, trajectory_figure
from src.visual_insights import state_map_insight, trajectory_insight


def _frame(rows: int = 40) -> pd.DataFrame:
    idx = np.arange(rows, dtype=float)
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    effort = np.sin(idx / 5.0)
    result = np.cos(idx / 6.0)
    direction = np.where(idx % 3 == 0, 1, np.where(idx % 3 == 1, -1, 0))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100 + idx,
            "high": 101 + idx,
            "low": 99 + idx,
            "close": 100.5 + idx,
            "volume": 1000 + idx,
            "delta": np.sin(idx) * 100,
            "delta_ratio": np.sin(idx) / 10,
            "oi": 5000 + idx,
            "oi_log_change": np.zeros(rows),
            "effort_raw": np.log1p(1000 + idx),
            "effort_score": effort,
            "result_raw": np.abs(result),
            "result_score": result,
            "directional_efficiency": np.full(rows, 0.5),
            "price_significance": effort,
            "delta_significance": result,
            "oi_significance": np.zeros(rows),
            "positioning_state": np.where(idx % 2 == 0, "Short Covering", "Mixed / Low Conviction"),
            "effort_result_region": np.where(effort >= 0, "High Effort / High Result", "Low Effort / Low Result"),
            "state_strength": np.sqrt(effort**2 + result**2),
            "state_velocity": np.r_[0.0, np.sqrt(np.diff(effort) ** 2 + np.diff(result) ** 2)],
            "bar_direction": direction,
            "lehr_short_pressure": False,
            "lehr_long_pressure": False,
            "helr_event": False,
            "near_state_boundary": False,
            "data_quality_flag": "",
        }
    )


def test_state_map_defaults_to_density_with_recent_overlay_and_current() -> None:
    figure = state_map_figure(_frame(), history=40, recent_points=12)
    assert figure.data[0].type == "histogram2dcontour"
    assert any(trace.name == "Recent path" for trace in figure.data)
    assert any(trace.name == "Current" for trace in figure.data)
    figure.to_json()


def test_state_map_full_scatter_and_positioning_color_serialize() -> None:
    figure = state_map_figure(_frame(), history=40, mode="Full scatter", color_by="Positioning")
    assert any(trace.name == "Short Covering" for trace in figure.data)
    assert any(trace.name == "Mixed / Low Conviction" for trace in figure.data)
    figure.to_json()


def test_trajectory_default_is_short_and_directional() -> None:
    figure = trajectory_figure(_frame(), trail_length=12)
    path = next(trace for trace in figure.data if trace.name == "Recent path")
    assert len(path.x) == 12
    assert any(trace.name == "Start" for trace in figure.data)
    assert any(trace.name == "Previous" for trace in figure.data)
    assert any(trace.name == "Current" for trace in figure.data)
    assert len(figure.layout.annotations) >= 5  # four quadrant labels plus latest-move arrow
    figure.to_json()


def test_trajectory_time_series_views_serialize() -> None:
    frame = _frame()
    for view in ("Effort over time", "Result over time", "Strength / Velocity"):
        figure = trajectory_figure(frame, trail_length=12, view=view)
        assert len(figure.data) >= 1
        figure.to_json()


def test_visual_insights_are_descriptive_and_boundary_aware() -> None:
    frame = _frame()
    frame.loc[frame.index[-1], "near_state_boundary"] = True
    state_text = state_map_insight(frame)
    trajectory_text = trajectory_insight(frame)
    assert "Current state:" in state_text
    assert "low confidence" in state_text
    assert "ΔE" in trajectory_text
    assert "ΔR" in trajectory_text
