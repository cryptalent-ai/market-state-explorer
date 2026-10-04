"""Plotly figures for state-space and chronological trajectory views."""

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


def _valid_state_rows(frame: pd.DataFrame, history: int) -> pd.DataFrame:
    return frame.dropna(subset=["effort_score", "result_score"]).tail(history).copy()


def _hover_text(frame: pd.DataFrame, timezone: str) -> list[str]:
    text: list[str] = []
    for _, row in frame.iterrows():
        oi_change = np.expm1(row["oi_log_change"]) if pd.notna(row["oi_log_change"]) else np.nan
        text.append(
            "<br>".join(
                [
                    f"Timestamp: {timestamp(row['timestamp'], timezone)}",
                    f"Open: {number(row['open'], 4)}",
                    f"High: {number(row['high'], 4)}",
                    f"Low: {number(row['low'], 4)}",
                    f"Close: {number(row['close'], 4)}",
                    f"Volume: {number(row['volume'], 2)}",
                    f"Delta: {number(row['delta'], 2, signed=True)}",
                    f"Delta / Volume: {number(row['delta_ratio'], 3, signed=True)}",
                    f"Open Interest: {number(row['oi'], 2)}",
                    f"OI Change: {percent(oi_change, 2, signed=True)}",
                    f"Effort Raw: {number(row['effort_raw'], 3)}",
                    f"Effort Score: {number(row['effort_score'], 2, signed=True)}",
                    f"Result Raw: {number(row['result_raw'], 3)}",
                    f"Result Score: {number(row['result_score'], 2, signed=True)}",
                    "Directional Efficiency: "
                    f"{number(row['directional_efficiency'], 3)}",
                    "Price Significance: "
                    f"{number(row['price_significance'], 2, signed=True)}",
                    "Delta Significance: "
                    f"{number(row['delta_significance'], 2, signed=True)}",
                    "OI Significance: "
                    f"{number(row['oi_significance'], 2, signed=True)}",
                    f"Positioning State: {row['positioning_state']}",
                    f"Effort–Result Region: {row['effort_result_region']}",
                    f"State Strength: {number(row['state_strength'], 2)}",
                    f"State Velocity: {number(row['state_velocity'], 2)}",
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
        margin={"l": 56, "r": 24, "t": 64, "b": 52},
        hoverlabel={"bgcolor": "#181818", "font": {"color": "#F5F5F5"}},
        dragmode="lasso",
    )
    figure.update_xaxes(gridcolor=GRID, zeroline=False)
    figure.update_yaxes(gridcolor=GRID, zeroline=False)
    return figure


def _quadrants(figure: go.Figure) -> None:
    figure.add_vline(x=0, line_width=1.5, line_color="#8A8A8A")
    figure.add_hline(y=0, line_width=1.5, line_color="#8A8A8A")
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
            font={"size": 11, "color": "#909090"},
        )


def state_map_figure(
    frame: pd.DataFrame,
    *,
    history: int = 500,
    timezone: str = "Asia/Taipei",
) -> go.Figure:
    """Build the Effort × Result scatter with complete state hover detail."""

    visible = _valid_state_rows(frame, history)
    figure = go.Figure()
    direction_styles = (
        (1, "Up bar", BULL, "triangle-up"),
        (-1, "Down bar", BEAR, "triangle-down"),
        (0, "Flat bar", NEUTRAL, "circle"),
    )
    for direction, label, color, symbol in direction_styles:
        subset = visible[visible["bar_direction"].eq(direction)]
        if subset.empty:
            continue
        oi_size = 8.0 + 6.0 * np.sqrt(
            subset["oi_significance"].abs().clip(upper=4).fillna(0)
        )
        figure.add_trace(
            go.Scattergl(
                x=subset["effort_score"],
                y=subset["result_score"],
                mode="markers",
                name=label,
                text=_hover_text(subset, timezone),
                hovertemplate="%{text}<extra></extra>",
                marker={
                    "color": color,
                    "size": oi_size,
                    "symbol": symbol,
                    "opacity": 0.68,
                    "line": {"width": 0.5, "color": "#151515"},
                },
                selected={"marker": {"opacity": 1.0, "size": 24}},
                unselected={"marker": {"opacity": 0.22}},
            )
        )
    if not visible.empty:
        current = visible.tail(1)
        figure.add_trace(
            go.Scatter(
                x=current["effort_score"],
                y=current["result_score"],
                mode="markers+text",
                name="Current",
                text=["Current"],
                textposition="top center",
                hovertext=_hover_text(current, timezone),
                hovertemplate="%{hovertext}<extra></extra>",
                marker={
                    "size": 20,
                    "symbol": "star",
                    "color": "#FFD54F",
                    "line": {"width": 2, "color": "#FFFFFF"},
                },
            )
        )
    _quadrants(figure)
    _base_layout(figure, "Effort–Result State Map")
    figure.update_xaxes(title="Effort (robust z-score)")
    figure.update_yaxes(title="Result (robust z-score)")
    return figure


def trajectory_figure(
    frame: pd.DataFrame,
    *,
    trail_length: int = 50,
    timezone: str = "Asia/Taipei",
) -> go.Figure:
    """Build a chronological state-space trail with event emphasis."""

    trail = _valid_state_rows(frame, trail_length)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=trail["effort_score"],
            y=trail["result_score"],
            mode="lines+markers",
            name="Chronological trail",
            text=_hover_text(trail, timezone),
            hovertemplate="%{text}<extra></extra>",
            line={"color": "#78909C", "width": 2},
            marker={
                "size": 7,
                "color": np.arange(len(trail)),
                "colorscale": [[0, "#455A64"], [1, "#ECEFF1"]],
                "showscale": False,
            },
        )
    )
    events = trail[
        trail[["lehr_short_pressure", "lehr_long_pressure", "helr_event"]]
        .fillna(False)
        .any(axis=1)
    ]
    if not events.empty:
        figure.add_trace(
            go.Scatter(
                x=events["effort_score"],
                y=events["result_score"],
                mode="markers",
                name="Research event",
                text=_hover_text(events, timezone),
                hovertemplate="%{text}<extra></extra>",
                marker={
                    "size": 14,
                    "symbol": "diamond-open",
                    "color": "#FFD54F",
                    "line": {"width": 2, "color": "#FFD54F"},
                },
            )
        )
    if len(trail) >= 2:
        previous = trail.iloc[[-2]]
        figure.add_trace(
            go.Scatter(
                x=previous["effort_score"],
                y=previous["result_score"],
                mode="markers",
                name="Previous",
                marker={"size": 14, "symbol": "circle-open", "color": "#FFFFFF"},
            )
        )
    if not trail.empty:
        current = trail.tail(1)
        figure.add_trace(
            go.Scatter(
                x=current["effort_score"],
                y=current["result_score"],
                mode="markers+text",
                name="Current",
                text=["Current"],
                textposition="top center",
                marker={
                    "size": 20,
                    "symbol": "star",
                    "color": "#FFD54F",
                    "line": {"width": 2, "color": "#FFFFFF"},
                },
            )
        )
    _quadrants(figure)
    _base_layout(figure, f"State Trajectory — Last {len(trail)} Valid Bars")
    figure.update_xaxes(title="Effort (robust z-score)")
    figure.update_yaxes(title="Result (robust z-score)")
    return figure


def candidate_stability_figure(frame: pd.DataFrame) -> go.Figure:
    """Compare the pre-specified candidate against baseline across sample windows."""

    figure = go.Figure()
    x = frame["Horizon"].astype(str)

    for label, suffix, color in (
        ("30-day", "30-Day", "#90A4AE"),
        ("12-month", "12-Month", "#FFD54F"),
    ):
        mean_col = f"Mean ATR Difference vs Baseline {suffix}"
        low_col = f"Difference vs Baseline ATR 95% CI Low {suffix}"
        high_col = f"Difference vs Baseline ATR 95% CI High {suffix}"
        means = frame[mean_col]
        plus = (frame[high_col] - means).clip(lower=0)
        minus = (means - frame[low_col]).clip(lower=0)
        figure.add_trace(
            go.Bar(
                x=x,
                y=means,
                name=label,
                marker={"color": color},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": plus,
                    "arrayminus": minus,
                    "visible": True,
                },
                hovertemplate=(
                    f"{label}<br>Horizon: %{{x}} bars"
                    "<br>Difference vs baseline: %{y:.3f} ATR<extra></extra>"
                ),
            )
        )

    figure.add_hline(x0=0, x1=1, y=0, line_width=1.5, line_color="#8A8A8A")
    _base_layout(figure, "Candidate Stability — Mean ATR Difference vs Baseline")
    figure.update_layout(barmode="group", dragmode="zoom")
    figure.update_xaxes(title="Forward horizon (bars)")
    figure.update_yaxes(title="Conditional mean − baseline mean (ATR)")
    return figure
