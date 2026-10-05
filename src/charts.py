"""Plotly figures for readable state-space and chronological trajectory views."""

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


def _valid_state_rows(frame: pd.DataFrame, history: int) -> pd.DataFrame:
    return frame.dropna(subset=["effort_score", "result_score"]).tail(history).copy()


def _hover_text(frame: pd.DataFrame, timezone: str) -> list[str]:
    text: list[str] = []
    for _, row in frame.iterrows():
        oi_change = np.expm1(row["oi_log_change"]) if pd.notna(row.get("oi_log_change")) else np.nan
        text.append(
            "<br>".join(
                [
                    f"Timestamp: {timestamp(row['timestamp'], timezone)}",
                    f"Open: {number(row.get('open'), 4)}",
                    f"High: {number(row.get('high'), 4)}",
                    f"Low: {number(row.get('low'), 4)}",
                    f"Close: {number(row.get('close'), 4)}",
                    f"Volume: {number(row.get('volume'), 2)}",
                    f"Delta: {number(row.get('delta'), 2, signed=True)}",
                    f"Delta / Volume: {number(row.get('delta_ratio'), 3, signed=True)}",
                    f"Open Interest: {number(row.get('oi'), 2)}",
                    f"OI Change: {percent(oi_change, 2, signed=True)}",
                    f"Effort Score: {number(row.get('effort_score'), 2, signed=True)}",
                    f"Result Score: {number(row.get('result_score'), 2, signed=True)}",
                    f"Positioning State: {row.get('positioning_state', '—')}",
                    f"Effort–Result Region: {row.get('effort_result_region', '—')}",
                    f"State Strength: {number(row.get('state_strength'), 2)}",
                    f"State Velocity: {number(row.get('state_velocity'), 2)}",
                ]
            )
        )
    return text


def _base_layout(figure: go.Figure, title: str, *, dragmode: str = "zoom") -> go.Figure:
    figure.update_layout(
        title=title,
        paper_bgcolor=CANVAS,
        plot_bgcolor=CANVAS,
        font={"color": "#E0E0E0", "family": "Inter, Arial, sans-serif"},
        margin={"l": 56, "r": 24, "t": 64, "b": 52},
        hoverlabel={"bgcolor": "#181818", "font": {"color": "#F5F5F5"}},
        dragmode=dragmode,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    figure.update_xaxes(gridcolor=GRID, zeroline=False)
    figure.update_yaxes(gridcolor=GRID, zeroline=False)
    return figure


def _quadrants(figure: go.Figure) -> None:
    figure.add_vline(x=0, line_width=1.2, line_color="#777777")
    figure.add_hline(y=0, line_width=1.2, line_color="#777777")
    labels = (
        (0.98, 0.98, "High Effort / High Result", "right", "top"),
        (0.98, 0.02, "High Effort / Low Result", "right", "bottom"),
        (0.02, 0.98, "Low Effort / High Result", "left", "top"),
        (0.02, 0.02, "Low Effort / Low Result", "left", "bottom"),
    )
    for x, y, label, xanchor, yanchor in labels:
        figure.add_annotation(
            x=x,
            y=y,
            xref="paper",
            yref="paper",
            text=label,
            showarrow=False,
            xanchor=xanchor,
            yanchor=yanchor,
            font={"size": 11, "color": "#8B8B8B"},
        )


def _add_recent_path(figure: go.Figure, recent: pd.DataFrame, timezone: str) -> None:
    if recent.empty:
        return
    figure.add_trace(
        go.Scatter(
            x=recent["effort_score"],
            y=recent["result_score"],
            mode="lines",
            name="Recent path",
            line={"color": RECENT_LINE, "width": 2},
            opacity=0.55,
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=recent["effort_score"],
            y=recent["result_score"],
            mode="markers",
            name=f"Recent {len(recent)}",
            text=_hover_text(recent, timezone),
            hovertemplate="%{text}<extra></extra>",
            marker={
                "size": 8,
                "color": np.arange(len(recent)),
                "colorscale": [[0, "#455A64"], [1, "#ECEFF1"]],
                "showscale": False,
                "opacity": 0.9,
                "line": {"width": 0.5, "color": "#151515"},
            },
        )
    )


def _add_semantic_points(
    figure: go.Figure,
    points: pd.DataFrame,
    timezone: str,
    *,
    color_by: str,
    opacity: float,
) -> None:
    if points.empty:
        return
    if color_by == "Positioning":
        for state, subset in points.groupby(points["positioning_state"].fillna("Unknown"), sort=False):
            figure.add_trace(
                go.Scattergl(
                    x=subset["effort_score"],
                    y=subset["result_score"],
                    mode="markers",
                    name=str(state),
                    text=_hover_text(subset, timezone),
                    hovertemplate="%{text}<extra></extra>",
                    marker={
                        "size": 7,
                        "color": POSITIONING_COLORS.get(str(state), NEUTRAL),
                        "opacity": opacity,
                    },
                )
            )
        return

    direction_styles = (
        (1, "Up bar", BULL, "triangle-up"),
        (-1, "Down bar", BEAR, "triangle-down"),
        (0, "Flat bar", NEUTRAL, "circle"),
    )
    for direction, label, color, symbol in direction_styles:
        subset = points[points["bar_direction"].eq(direction)]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scattergl(
                x=subset["effort_score"],
                y=subset["result_score"],
                mode="markers",
                name=label,
                text=_hover_text(subset, timezone),
                hovertemplate="%{text}<extra></extra>",
                marker={"size": 7, "color": color, "symbol": symbol, "opacity": opacity},
            )
        )


def _add_current(figure: go.Figure, current: pd.DataFrame, timezone: str) -> None:
    if current.empty:
        return
    row = current.iloc[-1]
    label = (
        f"Current  E {float(row['effort_score']):+.2f} · "
        f"R {float(row['result_score']):+.2f}"
    )
    figure.add_trace(
        go.Scatter(
            x=current["effort_score"],
            y=current["result_score"],
            mode="markers+text",
            name="Current",
            text=[label],
            textposition="top center",
            hovertext=_hover_text(current, timezone),
            hovertemplate="%{hovertext}<extra></extra>",
            marker={
                "size": 22,
                "symbol": "star",
                "color": CURRENT,
                "line": {"width": 2, "color": "#FFFFFF"},
            },
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
    """Build a readable Effort × Result map with historical density and recent context."""

    visible = _valid_state_rows(frame, history)
    recent = visible.tail(max(1, min(int(recent_points), len(visible))))
    figure = go.Figure()

    if mode == "Density + recent" and not visible.empty:
        figure.add_trace(
            go.Histogram2dContour(
                x=visible["effort_score"],
                y=visible["result_score"],
                name="Historical density",
                ncontours=12,
                colorscale=[
                    [0.0, "rgba(15,15,15,0.00)"],
                    [0.35, "rgba(84,110,122,0.18)"],
                    [0.7, "rgba(144,164,174,0.34)"],
                    [1.0, "rgba(236,239,241,0.55)"],
                ],
                contours={"coloring": "fill", "showlines": False},
                showscale=False,
                hoverinfo="skip",
            )
        )
        _add_recent_path(figure, recent, timezone)
    elif mode == "Recent only":
        _add_recent_path(figure, recent, timezone)
    else:
        _add_semantic_points(figure, visible, timezone, color_by=color_by, opacity=0.45)
        _add_recent_path(figure, recent, timezone)

    _add_current(figure, visible.tail(1), timezone)
    _quadrants(figure)
    _base_layout(figure, f"Effort–Result State Map — {mode}", dragmode="zoom")
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
    """Build a compact trajectory or time-series view for recent valid states."""

    trail = _valid_state_rows(frame, trail_length)
    figure = go.Figure()
    if trail.empty:
        return _base_layout(figure, "State Trajectory")

    timestamps = pd.to_datetime(trail["timestamp"], utc=True).dt.tz_convert(timezone)
    hover = _hover_text(trail, timezone)

    if view == "Effort over time":
        figure.add_trace(go.Scatter(
            x=timestamps, y=trail["effort_score"], mode="lines+markers", name="Effort",
            text=hover, hovertemplate="%{text}<extra></extra>",
            line={"width": 2}, marker={"size": 7},
        ))
        figure.add_hline(y=0, line_width=1.2, line_color="#777777")
        _base_layout(figure, f"Effort over Time — Last {len(trail)} Valid States")
        figure.update_yaxes(title="Effort (robust z-score)")
        figure.update_xaxes(title=None)
        return figure

    if view == "Result over time":
        figure.add_trace(go.Scatter(
            x=timestamps, y=trail["result_score"], mode="lines+markers", name="Result",
            text=hover, hovertemplate="%{text}<extra></extra>",
            line={"width": 2}, marker={"size": 7},
        ))
        figure.add_hline(y=0, line_width=1.2, line_color="#777777")
        _base_layout(figure, f"Result over Time — Last {len(trail)} Valid States")
        figure.update_yaxes(title="Result (robust z-score)")
        figure.update_xaxes(title=None)
        return figure

    if view == "Strength / Velocity":
        figure.add_trace(go.Scatter(
            x=timestamps, y=trail["state_strength"], mode="lines+markers", name="Strength",
            line={"width": 2}, marker={"size": 7},
        ))
        figure.add_trace(go.Scatter(
            x=timestamps, y=trail["state_velocity"], mode="lines+markers", name="Velocity",
            line={"width": 2}, marker={"size": 7},
        ))
        _base_layout(figure, f"State Strength & Velocity — Last {len(trail)} Valid States")
        figure.update_yaxes(title="Score")
        figure.update_xaxes(title=None)
        return figure

    figure.add_trace(
        go.Scatter(
            x=trail["effort_score"],
            y=trail["result_score"],
            mode="lines+markers",
            name="Recent path",
            text=hover,
            hovertemplate="%{text}<extra></extra>",
            line={"color": RECENT_LINE, "width": 2.4},
            marker={
                "size": 8,
                "color": np.arange(len(trail)),
                "colorscale": [[0, "#455A64"], [1, "#ECEFF1"]],
                "showscale": False,
            },
        )
    )
    first = trail.head(1)
    figure.add_trace(go.Scatter(
        x=first["effort_score"], y=first["result_score"], mode="markers", name="Start",
        marker={"size": 11, "symbol": "square-open", "color": "#B0BEC5", "line": {"width": 1.5}},
    ))
    if len(trail) >= 2:
        previous = trail.iloc[[-2]]
        current = trail.tail(1)
        figure.add_trace(go.Scatter(
            x=previous["effort_score"], y=previous["result_score"], mode="markers", name="Previous",
            marker={"size": 13, "symbol": "circle-open", "color": "#FFFFFF", "line": {"width": 1.5}},
        ))
        figure.add_annotation(
            x=float(current.iloc[0]["effort_score"]),
            y=float(current.iloc[0]["result_score"]),
            ax=float(previous.iloc[0]["effort_score"]),
            ay=float(previous.iloc[0]["result_score"]),
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=2, arrowcolor=CURRENT,
            text="",
        )
    _add_current(figure, trail.tail(1), timezone)
    _quadrants(figure)
    _base_layout(figure, f"State Trajectory — Last {len(trail)} Valid States")
    figure.update_xaxes(title="Effort (robust z-score)")
    figure.update_yaxes(title="Result (robust z-score)")
    return figure


def candidate_stability_figure(frame: pd.DataFrame) -> go.Figure:
    """Compare the pre-specified candidate against baseline across sample windows."""

    figure = go.Figure()
    x = frame["Horizon"].astype(str)
    for label, suffix, color in (
        ("30-day", "30-Day", "#90A4AE"),
        ("12-month", "12-Month", CURRENT),
    ):
        mean_col = f"Mean ATR Difference vs Baseline {suffix}"
        low_col = f"Difference vs Baseline ATR 95% CI Low {suffix}"
        high_col = f"Difference vs Baseline ATR 95% CI High {suffix}"
        means = frame[mean_col]
        plus = (frame[high_col] - means).clip(lower=0)
        minus = (means - frame[low_col]).clip(lower=0)
        figure.add_trace(go.Bar(
            x=x, y=means, name=label, marker={"color": color},
            error_y={"type": "data", "symmetric": False, "array": plus, "arrayminus": minus, "visible": True},
            hovertemplate=f"{label}<br>Horizon: %{{x}} bars<br>Difference vs baseline: %{{y:.3f}} ATR<extra></extra>",
        ))
    figure.add_hline(y=0, line_width=1.5, line_color="#8A8A8A")
    _base_layout(figure, "Candidate Stability — Mean ATR Difference vs Baseline")
    figure.update_layout(barmode="group")
    figure.update_xaxes(title="Forward horizon (bars)")
    figure.update_yaxes(title="Conditional mean − baseline mean (ATR)")
    return figure
