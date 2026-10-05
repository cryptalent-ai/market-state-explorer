"""Versioned v1.2 chart module used by the Streamlit visual-clarity UI.

This module is deliberately separate from ``src.charts`` so Streamlit hot-reload
cannot retain the v1.1 function signatures while loading the v1.2 page code.
It also normalizes chart-facing numeric dtypes defensively because hosted/archive
frames may arrive with object/string columns even though the underlying values are
numeric.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .formatting import number, percent, timestamp

CANVAS = "#0F0F0F"
GRID = "#2A2A2A"
BULL = "#43A047"
BEAR = "#D32F2F"
NEUTRAL = "#B0BEC5"
CURRENT = "#FFD54F"
RECENT_LINE = "#78909C"
POSITIONING_COLORS = {
    "New Long Initiative": "#66BB6A",
    "Short Covering": "#26A69A",
    "Aggressive Shorts Absorbed": "#9CCC65",
    "Bullish Price-Flow Divergence": "#42A5F5",
    "New Short Initiative": "#EF5350",
    "Long Liquidation / Closing": "#FF7043",
    "Aggressive Buyers Absorbed": "#AB47BC",
    "Bearish Price-Flow Divergence": "#EC407A",
    "Mixed / Low Conviction": "#90A4AE",
}

_NUMERIC_COLUMNS = (
    "open", "high", "low", "close", "volume", "delta", "delta_ratio", "oi",
    "oi_log_change", "effort_score", "result_score", "state_strength",
    "state_velocity", "bar_direction",
)


def _prepared(frame: pd.DataFrame, history: int) -> pd.DataFrame:
    out = frame.copy()
    for column in _NUMERIC_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    return out.dropna(subset=["effort_score", "result_score"]).tail(history).copy()


def _safe_oi_change(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if not np.isfinite(numeric):
        return float("nan")
    return float(np.expm1(numeric))


def _hover_text(frame: pd.DataFrame, timezone: str) -> list[str]:
    text: list[str] = []
    for _, row in frame.iterrows():
        text.append(
            "<br>".join(
                [
                    f"Timestamp: {timestamp(row.get('timestamp'), timezone)}",
                    f"Effort: {number(row.get('effort_score'), 2, signed=True)}",
                    f"Result: {number(row.get('result_score'), 2, signed=True)}",
                    f"Region: {row.get('effort_result_region', '—')}",
                    f"Positioning: {row.get('positioning_state', '—')}",
                    f"Strength: {number(row.get('state_strength'), 2)}",
                    f"Velocity: {number(row.get('state_velocity'), 2)}",
                    f"Close: {number(row.get('close'), 4)}",
                    f"Delta / Volume: {number(row.get('delta_ratio'), 3, signed=True)}",
                    f"OI Change: {percent(_safe_oi_change(row.get('oi_log_change')), 2, signed=True)}",
                ]
            )
        )
    return text


def _base_layout(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=title,
        paper_bgcolor=CANVAS,
        plot_bgcolor=CANVAS,
        font={"color": "#E0E0E0", "family": "Inter, Arial, sans-serif"},
        margin={"l": 56, "r": 24, "t": 76, "b": 52},
        hoverlabel={"bgcolor": "#181818", "font": {"color": "#F5F5F5"}},
        dragmode="zoom",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    figure.update_xaxes(gridcolor=GRID, zeroline=False)
    figure.update_yaxes(gridcolor=GRID, zeroline=False)
    return figure


def _quadrants(figure: go.Figure) -> None:
    figure.add_vline(x=0, line_width=1.2, line_color="#777777")
    figure.add_hline(y=0, line_width=1.2, line_color="#777777")
    for x, y, label, xa, ya in (
        (0.98, 0.98, "High Effort / High Result", "right", "top"),
        (0.98, 0.02, "High Effort / Low Result", "right", "bottom"),
        (0.02, 0.98, "Low Effort / High Result", "left", "top"),
        (0.02, 0.02, "Low Effort / Low Result", "left", "bottom"),
    ):
        figure.add_annotation(
            x=x, y=y, xref="paper", yref="paper", text=label, showarrow=False,
            xanchor=xa, yanchor=ya, font={"size": 11, "color": "#8B8B8B"},
        )


def _add_recent(figure: go.Figure, recent: pd.DataFrame, timezone: str) -> None:
    if recent.empty:
        return
    figure.add_trace(
        go.Scatter(
            x=recent["effort_score"], y=recent["result_score"], mode="lines",
            name="Recent path", line={"color": RECENT_LINE, "width": 2},
            opacity=0.55, hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=recent["effort_score"], y=recent["result_score"], mode="markers",
            name=f"Recent {len(recent)}", text=_hover_text(recent, timezone),
            hovertemplate="%{text}<extra></extra>",
            marker={
                "size": 8,
                "color": list(range(len(recent))),
                "colorscale": [[0, "#455A64"], [1, "#ECEFF1"]],
                "showscale": False,
                "opacity": 0.9,
            },
        )
    )


def _add_current(figure: go.Figure, current: pd.DataFrame, timezone: str) -> None:
    if current.empty:
        return
    row = current.iloc[-1]
    label = f"Current  E {float(row['effort_score']):+.2f} · R {float(row['result_score']):+.2f}"
    figure.add_trace(
        go.Scatter(
            x=current["effort_score"], y=current["result_score"], mode="markers+text",
            name="Current", text=[label], textposition="top center",
            hovertext=_hover_text(current, timezone), hovertemplate="%{hovertext}<extra></extra>",
            marker={"size": 22, "symbol": "star", "color": CURRENT, "line": {"width": 2, "color": "#FFFFFF"}},
        )
    )


def _add_full_scatter(figure: go.Figure, visible: pd.DataFrame, timezone: str, color_by: str) -> None:
    if color_by == "Positioning" and "positioning_state" in visible.columns:
        states = visible["positioning_state"].fillna("Unknown")
        for state, subset in visible.groupby(states, sort=False):
            figure.add_trace(
                go.Scattergl(
                    x=subset["effort_score"], y=subset["result_score"], mode="markers",
                    name=str(state), text=_hover_text(subset, timezone),
                    hovertemplate="%{text}<extra></extra>",
                    marker={"size": 7, "color": POSITIONING_COLORS.get(str(state), NEUTRAL), "opacity": 0.42},
                )
            )
        return

    direction = visible.get("bar_direction", pd.Series(index=visible.index, dtype=float))
    for value, label, color, symbol in (
        (1, "Up bar", BULL, "triangle-up"),
        (-1, "Down bar", BEAR, "triangle-down"),
        (0, "Flat bar", NEUTRAL, "circle"),
    ):
        subset = visible[direction.eq(value)]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scattergl(
                x=subset["effort_score"], y=subset["result_score"], mode="markers",
                name=label, text=_hover_text(subset, timezone), hovertemplate="%{text}<extra></extra>",
                marker={"size": 7, "color": color, "symbol": symbol, "opacity": 0.42},
            )
        )


def state_map_figure(
    frame: pd.DataFrame,
    *,
    history: int = 500,
    timezone: str = "Asia/Taipei",
    mode: str = "Density + recent",
    recent_points: int = 20,
    color_by: str = "Direction",
) -> go.Figure:
    visible = _prepared(frame, history)
    recent = visible.tail(max(1, min(int(recent_points), len(visible))))
    figure = go.Figure()

    if mode == "Density + recent" and not visible.empty:
        figure.add_trace(
            go.Histogram2d(
                x=visible["effort_score"], y=visible["result_score"],
                name="Historical density", nbinsx=32, nbinsy=32,
                colorscale=[[0, "#0F0F0F"], [0.35, "#263238"], [0.7, "#546E7A"], [1, "#B0BEC5"]],
                showscale=False, hoverinfo="skip", opacity=0.72,
            )
        )
        _add_recent(figure, recent, timezone)
    elif mode == "Recent only":
        _add_recent(figure, recent, timezone)
    else:
        _add_full_scatter(figure, visible, timezone, color_by)
        _add_recent(figure, recent, timezone)

    _add_current(figure, visible.tail(1), timezone)
    _quadrants(figure)
    _base_layout(figure, f"Effort–Result State Map — {mode}")
    figure.update_xaxes(title="Effort (robust z-score)")
    figure.update_yaxes(title="Result (robust z-score)")
    return figure


def trajectory_figure(
    frame: pd.DataFrame,
    *,
    trail_length: int = 12,
    timezone: str = "Asia/Taipei",
    view: str = "2D trajectory",
) -> go.Figure:
    trail = _prepared(frame, trail_length)
    figure = go.Figure()
    if trail.empty:
        return _base_layout(figure, "State Trajectory")

    times = pd.to_datetime(trail["timestamp"], utc=True, errors="coerce").dt.tz_convert(timezone)
    hover = _hover_text(trail, timezone)

    if view in {"Effort over time", "Result over time"}:
        column = "effort_score" if view.startswith("Effort") else "result_score"
        label = "Effort" if column == "effort_score" else "Result"
        figure.add_trace(
            go.Scatter(
                x=times, y=trail[column], mode="lines+markers", name=label,
                text=hover, hovertemplate="%{text}<extra></extra>",
                line={"width": 2}, marker={"size": 7},
            )
        )
        figure.add_hline(y=0, line_width=1.2, line_color="#777777")
        _base_layout(figure, f"{label} over Time — Last {len(trail)} Valid States")
        figure.update_yaxes(title=f"{label} (robust z-score)")
        return figure

    if view == "Strength / Velocity":
        figure.add_trace(go.Scatter(x=times, y=trail["state_strength"], mode="lines+markers", name="Strength"))
        figure.add_trace(go.Scatter(x=times, y=trail["state_velocity"], mode="lines+markers", name="Velocity"))
        _base_layout(figure, f"State Strength & Velocity — Last {len(trail)} Valid States")
        figure.update_yaxes(title="Score")
        return figure

    figure.add_trace(
        go.Scatter(
            x=trail["effort_score"], y=trail["result_score"], mode="lines+markers",
            name="Recent path", text=hover, hovertemplate="%{text}<extra></extra>",
            line={"color": RECENT_LINE, "width": 2.4},
            marker={"size": 8, "color": list(range(len(trail))), "colorscale": [[0, "#455A64"], [1, "#ECEFF1"]], "showscale": False},
        )
    )
    first = trail.head(1)
    figure.add_trace(go.Scatter(
        x=first["effort_score"], y=first["result_score"], mode="markers", name="Start",
        marker={"size": 11, "symbol": "square-open", "color": "#B0BEC5"},
    ))
    if len(trail) >= 2:
        previous = trail.iloc[[-2]]
        current = trail.tail(1)
        figure.add_trace(go.Scatter(
            x=previous["effort_score"], y=previous["result_score"], mode="markers", name="Previous",
            marker={"size": 13, "symbol": "circle-open", "color": "#FFFFFF"},
        ))
        figure.add_annotation(
            x=float(current.iloc[0]["effort_score"]), y=float(current.iloc[0]["result_score"]),
            ax=float(previous.iloc[0]["effort_score"]), ay=float(previous.iloc[0]["result_score"]),
            xref="x", yref="y", axref="x", ayref="y", showarrow=True,
            arrowhead=3, arrowsize=1.2, arrowwidth=2, arrowcolor=CURRENT, text="",
        )
    _add_current(figure, trail.tail(1), timezone)
    _quadrants(figure)
    _base_layout(figure, f"State Trajectory — Last {len(trail)} Valid States")
    figure.update_xaxes(title="Effort (robust z-score)")
    figure.update_yaxes(title="Result (robust z-score)")
    return figure
