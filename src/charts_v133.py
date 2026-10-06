"""Discrete-state visualizations. Read derived values; never reconstruct a state.

Only the last comparable pair gets a vector in Effort–Result space. Lines in
the time panels are reading guides, broken at missing bars/segment boundaries.
They are not observations of continuous market traversal.
"""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .charts_v12 import CURRENT, _add_full_scatter, _base_layout, _hover_text, _quadrants
from .state_views import _adjacent, build_timeline_frame, prepare_state_frame

DISCRETE_STATE_NOTE = (
    "Market observations are discrete sampled states. "
    "Straight-line interpolation between historical observations is not interpreted "
    "as an observed continuous market path."
)


def _markers(recent: pd.DataFrame, timezone: str) -> list[go.Scatter]:
    """Partition the window: each sampled state appears exactly once."""
    traces = []
    older = recent.iloc[:-2] if len(recent) > 1 else recent.iloc[:0]
    if len(older):
        traces.append(go.Scatter(
            x=older.effort_score, y=older.result_score, mode="markers",
            name="Older recent states", meta="recent-observations",
            text=_hover_text(older, timezone), hovertemplate="%{text}<extra></extra>",
            marker=dict(size=np.linspace(6, 11, len(older)).tolist(),
                        color=list(range(len(older))), cmin=0, cmax=max(1, len(older)-1),
                        colorscale=[[0, "#526575"], [1, "#DAE8F4"]], showscale=False),
        ))
    for name, subset, symbol, size, color in (
        ("Previous", recent.iloc[-2:-1], "circle-open", 17, "#FFFFFF"),
        ("Current", recent.tail(1), "star", 25, CURRENT),
    ):
        if subset.empty:
            continue
        traces.append(go.Scatter(
            x=subset.effort_score, y=subset.result_score, mode="markers+text",
            name=name, meta="recent-observations", text=[name], textposition="top center",
            textfont=dict(color=color, size=13), cliponaxis=False,
            hovertext=_hover_text(subset, timezone), hovertemplate="%{hovertext}<extra></extra>",
            marker=dict(symbol=symbol, size=size, color=color, line=dict(width=2, color="#FFFFFF")),
        ))
    return traces


def _latest_vector(figure: go.Figure, recent: pd.DataFrame) -> None:
    if len(recent) < 2 or not _adjacent(recent).iloc[-1]:
        return
    previous, current = recent.iloc[-2], recent.iloc[-1]
    if (previous.effort_score, previous.result_score) == (current.effort_score, current.result_score):
        return  # Zero displacement has no direction; do not fabricate an arrow.
    figure.add_annotation(
        name="Latest move", x=float(current.effort_score), y=float(current.result_score),
        ax=float(previous.effort_score), ay=float(previous.result_score),
        xref="x", yref="y", axref="x", ayref="y", text="", showarrow=True,
        arrowhead=3, arrowsize=1.3, arrowwidth=2.5, arrowcolor=CURRENT,
        standoff=12, startstandoff=9,
    )
    # Legend key only; no fabricated observation and no extra line trace.
    figure.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers", name="Latest move", meta="legend-only",
        marker=dict(symbol="triangle-right", size=12, color=CURRENT), hoverinfo="skip",
    ))


def state_map_figure(
    frame: pd.DataFrame, *, history: int | None = 500, timezone: str = "Asia/Taipei",
    mode: str = "Density + recent", recent_points: int = 20, color_by: str = "Direction",
    snapshot: bool = False,
) -> go.Figure:
    prepared = prepare_state_frame(frame)
    visible = prepared if history is None else prepared.tail(max(0, history))
    recent = visible.tail(max(0, recent_points))
    figure = go.Figure()
    if mode == "Density + recent" and not visible.empty and not snapshot:
        figure.add_trace(go.Histogram2d(
            x=visible.effort_score, y=visible.result_score, name="Historical density",
            nbinsx=32, nbinsy=32, showscale=False, hoverinfo="skip", opacity=.72,
            colorscale=[[0, "#0F0F0F"], [.35, "#263238"], [.7, "#546E7A"], [1, "#B0BEC5"]],
        ))
    elif mode == "Full scatter" and not snapshot:
        _add_full_scatter(figure, visible, timezone, color_by)
    for trace in _markers(recent, timezone):
        figure.add_trace(trace)
    _latest_vector(figure, recent)
    _quadrants(figure)
    title = "2D Snapshot Cloud" if snapshot else f"Effort–Result State Map — {mode}"
    if not recent.empty:
        current = recent.iloc[-1]
        title += (f"<br><sup>Current · Effort {current.effort_score:+.2f} · "
                  f"Result {current.result_score:+.2f} · {escape(current.effort_result_region)}</sup>")
    _base_layout(figure, title)
    figure.update_layout(height=590, margin=dict(t=120), legend=dict(itemsizing="constant"))
    extent = recent if mode == "Recent only" or snapshot else visible
    for axis, column, label in (("x", "effort_score", "Effort"), ("y", "result_score", "Result")):
        limit = max(1., float(extent[column].abs().max())) * 1.2 if not extent.empty else 1.
        figure.update_layout(**{f"{axis}axis": dict(
            title=f"{label} (robust z-score)", range=[-limit, limit],
        )})
    return figure


def snapshot_cloud_figure(frame: pd.DataFrame, *, recent_n: int = 12, timezone: str = "Asia/Taipei") -> go.Figure:
    return state_map_figure(frame, history=None, mode="Recent only", recent_points=recent_n,
                            timezone=timezone, snapshot=True)


def effort_result_time_figure(frame: pd.DataFrame, *, recent_n: int = 12, timezone: str = "Asia/Taipei") -> go.Figure:
    recent = build_timeline_frame(frame, recent_n)
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.12,
                          subplot_titles=("Effort robust z-score", "Result robust z-score"))
    times = recent.timestamp.dt.tz_convert(timezone).tolist()
    adjacent = _adjacent(recent)
    for panel, column, label, color in (
        (1, "effort_score", "Effort", "#79B8FF"), (2, "result_score", "Result", "#66D7BE"),
    ):
        # Keep the marker trace exact, including gaps; separate, discontinuous
        # time guides cannot imply traversal across a missing observation.
        line_x, line_y = [], []
        for i, (time, value) in enumerate(zip(times, recent[column])):
            if i and not adjacent.iloc[i]:
                line_x.append(None)
                line_y.append(None)
            line_x.append(time)
            line_y.append(value)
        figure.add_trace(go.Scatter(
            x=line_x, y=line_y, mode="lines", name=f"{label} time guide", meta="time-guide",
            line=dict(color=color, width=1.5), connectgaps=False, showlegend=False, hoverinfo="skip",
        ), row=panel, col=1)
        figure.add_trace(go.Scatter(
            x=times, y=recent[column].tolist(), mode="markers", name=label, meta="time-observations",
            text=_hover_text(recent, timezone), hovertemplate="%{text}<extra></extra>",
            marker=dict(size=8, color=color),
        ), row=panel, col=1)
        for name, offset, symbol, size, marker_color in (
            ("Previous", -2, "circle-open", 17, "#FFFFFF"),
            ("Current", -1, "star", 23, CURRENT),
        ):
            if len(recent) < abs(offset):
                continue
            figure.add_trace(go.Scatter(
                x=[times[offset]], y=[recent.iloc[offset][column]], mode="markers+text",
                name=name, legendgroup=name, showlegend=panel == 1,
                text=[name], textposition="top center", cliponaxis=False,
                textfont=dict(color=marker_color), hovertext=_hover_text(recent.iloc[[offset]], timezone),
                hovertemplate="%{hovertext}<extra></extra>",
                marker=dict(symbol=symbol, size=size, color=marker_color, line=dict(width=2, color="#FFFFFF")),
            ), row=panel, col=1)
        figure.add_hline(y=0, line_color="#777777", line_width=1.2, row=panel, col=1)
        figure.update_yaxes(title_text=f"{label} (robust z-score)", row=panel, col=1)
    _base_layout(figure, f"Effort / Result over Time — Last {len(recent)} Valid States")
    figure.update_layout(height=600, hovermode="closest", margin=dict(t=105))
    figure.update_xaxes(type="date", tickformat="%H:%M\n%Y-%m-%d")
    figure.update_xaxes(title_text=f"Actual observation timestamp · {timezone}", row=2, col=1)
    return figure
