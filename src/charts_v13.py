"""Categorical and chronological figures for already-derived states only."""
from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .charts_v12 import CANVAS, CURRENT, GRID, POSITIONING_COLORS
from .formatting import number, timestamp
from .state_views import (
    boundary_label, build_timeline_frame, compute_region_occupancy,
    research_label,
)

REGION_COLORS = {
    "Low Effort / High Result": "#9C93D3",
    "High Effort / High Result": "#61A5C2",
    "Low Effort / Low Result": "#929EAA",
    "High Effort / Low Result": "#CCAC78",
}


def _layout(figure: go.Figure, height: int) -> go.Figure:
    figure.update_layout(height=height, paper_bgcolor=CANVAS, plot_bgcolor=CANVAS,
                         font=dict(color="#EAEAEA", family="Arial, sans-serif"),
                         margin=dict(l=20, r=20, t=28, b=30), showlegend=False,
                         hoverlabel=dict(bgcolor="#202020", font_color="#FFFFFF"))
    return figure


def state_matrix_figure(frame: pd.DataFrame, history: int | None = 500, recent_n: int = 12) -> go.Figure:
    occupancy = compute_region_occupancy(frame, history, recent_n).set_index("Region")
    figure = _layout(go.Figure(), 300)
    cells = ((0, 1, "Low Effort / High Result"), (1, 1, "High Effort / High Result"),
             (0, 0, "Low Effort / Low Result"), (1, 0, "High Effort / Low Result"))
    for x, y, region in cells:
        row = occupancy.loc[region]
        color = REGION_COLORS[region]
        rgb = ",".join(str(int(color[i:i+2], 16)) for i in (1, 3, 5))
        figure.add_shape(type="rect", x0=x-.48, x1=x+.48, y0=y-.46, y1=y+.46,
                         fillcolor=f"rgba({rgb},0.16)",
                         line=dict(color=CURRENT if row["Current"] else color, width=3 if row["Current"] else 1))
        text = f"<b>{region}</b><br>History: {number(row['Historical %'], 1)}% · N={int(row['Historical N'])}<br>Recent {int(row['Recent N'])}: {int(row['Recent count'])} / {int(row['Recent N'])} ({number(row['Recent %'], 1)}%)"
        if row["Current"]:
            text += "<br><b>★ CURRENT / LATEST</b>"
        figure.add_annotation(x=x, y=y, text=text, showarrow=False, font=dict(size=13))
    figure.update_xaxes(range=[-.5, 1.5], tickvals=[0, 1], ticktext=["Low Effort", "High Effort"], fixedrange=True, showgrid=False, zeroline=False)
    figure.update_yaxes(range=[-.5, 1.5], tickvals=[0, 1], ticktext=["Low Result", "High Result"], fixedrange=True, showgrid=False, zeroline=False)
    figure.update_layout(margin=dict(l=90, r=15, t=5, b=35))
    return figure


def timeline_ribbon_figure(frame: pd.DataFrame, recent_n: int = 12, timezone: str = "Asia/Taipei") -> go.Figure:
    recent = build_timeline_frame(frame, recent_n)
    figure = _layout(go.Figure(), 250)
    if recent.empty:
        return figure
    categories = list(REGION_COLORS) + list(POSITIONING_COLORS) + ["None", "Research event", "Unavailable", "Near zero boundary", "Not near zero boundary", "Boundary unavailable"]
    colors = list(REGION_COLORS.values()) + list(POSITIONING_COLORS.values()) + ["#444B52", "#C7B477", "#303438", "#B9B2A0", "#444B52", "#303438"]
    lookup = {name: i for i, name in enumerate(categories)}
    scale = []
    for i, color in enumerate(colors):
        scale.extend([(i/len(colors), color), ((i+1)/len(colors), color)])
    z = [[], [], [], []]
    details = []
    for _, row in recent.iterrows():
        research, boundary = research_label(row), boundary_label(row)
        z[0].append(lookup.get(row["effort_result_region"], lookup["Unavailable"]))
        z[1].append(lookup.get(row["positioning_state"], lookup["Unavailable"]))
        z[2].append(lookup[research if research in ("None", "Unavailable") else "Research event"])
        z[3].append(lookup[boundary])
        details.append("<br>".join((escape(timestamp(row["timestamp"], timezone)),
            "Region: " + escape(row["effort_result_region"]), "Positioning: " + escape(row["positioning_state"]),
            "Research: " + escape(research), escape(boundary),
            f"Effort {number(row['effort_score'], 2)} · Result {number(row['result_score'], 2)}",
            f"Strength {number(row['state_strength'], 2)} · Velocity {number(row['state_velocity'], 2)}")))
    labels = ["Region", "Positioning", "Research Event", "Zero boundary"]
    figure.add_trace(go.Heatmap(x=list(range(len(recent))), y=labels, z=z, zmin=-.5,
                               zmax=len(colors)-.5, colorscale=scale, showscale=False,
                               xgap=3, ygap=5, customdata=[details]*4,
                               hovertemplate="%{customdata}<extra></extra>"))
    latest = len(recent)-1
    figure.add_shape(type="rect", x0=latest-.5, x1=latest+.5, y0=-.5, y1=3.5,
                     line=dict(color=CURRENT, width=3), fillcolor="rgba(0,0,0,0)")
    figure.add_annotation(x=latest, y=1.08, yref="paper", text="★ LATEST", showarrow=False, font_color=CURRENT, xanchor="right")
    ticks = sorted({0, latest//2, latest})
    figure.update_xaxes(tickvals=ticks, ticktext=[timestamp(recent.iloc[i]["timestamp"], timezone) for i in ticks],
                        range=[-.5, latest+.5], fixedrange=True, showgrid=False)
    figure.update_yaxes(autorange="reversed", fixedrange=True, showgrid=False)
    figure.update_layout(margin=dict(l=115, r=15, t=32, b=40))
    return figure


def small_multiples_figure(frame: pd.DataFrame, recent_n: int = 12, timezone: str = "Asia/Taipei") -> go.Figure:
    recent = build_timeline_frame(frame, recent_n)
    figure = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.08,
                          subplot_titles=("Effort", "Result", "Strength", "Velocity"))
    _layout(figure, 650)
    dates = recent["timestamp"].dt.tz_convert(timezone)
    for i, column in enumerate(("effort_score", "result_score", "state_strength", "state_velocity"), start=1):
        figure.add_trace(go.Scatter(x=dates, y=recent[column], mode="lines+markers", name=column,
                                   line_color="#A7B5C4", connectgaps=False), row=i, col=1)
        if len(recent):
            figure.add_trace(go.Scatter(x=dates.iloc[-1:], y=recent[column].iloc[-1:], mode="markers",
                                       marker=dict(color=CURRENT, size=12, symbol="star"), name="Latest"), row=i, col=1)
        if i <= 2:
            figure.add_hline(y=0, line_color="#8A8A8A", line_dash="dot", row=i, col=1)
        figure.update_yaxes(gridcolor=GRID, zeroline=False, row=i, col=1)
    figure.update_xaxes(gridcolor=GRID, title_text=f"Time ({timezone})", row=4, col=1)
    figure.update_layout(margin=dict(l=60, r=15, t=40, b=45))
    return figure
