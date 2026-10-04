"""Reusable Streamlit presentation helpers for the production web app."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .formatting import number


def candidate_chart(frame: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    x = frame["Horizon"].astype(str)
    for label, suffix, color in (
        ("30-day", "30-Day", "#90A4AE"),
        ("12-month", "12-Month", "#FFD54F"),
    ):
        mean = frame[f"Mean ATR Difference vs Baseline {suffix}"]
        low = frame[f"Difference vs Baseline ATR 95% CI Low {suffix}"]
        high = frame[f"Difference vs Baseline ATR 95% CI High {suffix}"]
        fig.add_bar(
            x=x, y=mean, name=label, marker_color=color,
            error_y=dict(type="data", symmetric=False,
                         array=(high - mean).clip(lower=0),
                         arrayminus=(mean - low).clip(lower=0), visible=True),
            hovertemplate=(f"{label}<br>Horizon: %{{x}} bars"
                           "<br>Difference vs baseline: %{y:.3f} ATR<extra></extra>"),
        )
    fig.add_hline(y=0, line_width=1.5, line_color="#8A8A8A")
    fig.update_layout(
        title="Candidate Stability — Mean ATR Difference vs Baseline",
        paper_bgcolor="#0F0F0F", plot_bgcolor="#0F0F0F", font_color="#E0E0E0",
        barmode="group", xaxis_title="Forward horizon (bars)",
        yaxis_title="Conditional mean − baseline mean (ATR)",
        margin=dict(l=48, r=24, t=64, b=48),
    )
    fig.update_xaxes(gridcolor="#2A2A2A", type="category",
                     categoryorder="array", categoryarray=x.tolist())
    fig.update_yaxes(gridcolor="#2A2A2A")
    return fig


def validation_chart(frame: pd.DataFrame, ranking: str) -> go.Figure:
    data = frame.dropna(subset=["Mean ATR Difference vs Baseline"]).copy()
    if data.empty:
        return go.Figure()
    data["Label"] = (data["Group"].astype(str) + " · "
                     + data["Positioning State"].astype(str) + " · H"
                     + data["Horizon"].astype(str))
    metric = data["Mean ATR Difference vs Baseline"]
    if ranking == "Most negative":
        data = data.assign(_rank=metric).sort_values("_rank").head(15)
    elif ranking == "Largest absolute":
        data = data.assign(_rank=metric.abs()).sort_values("_rank", ascending=False).head(15)
    else:
        data = data.assign(_rank=metric).sort_values("_rank", ascending=False).head(15)
    fig = go.Figure(go.Bar(
        x=data["Mean ATR Difference vs Baseline"], y=data["Label"], orientation="h",
        customdata=data[["Non-Overlapping N", "Sample Quality"]],
        hovertemplate=("%{y}<br>Difference: %{x:.3f} ATR<br>N: %{customdata[0]}"
                       "<br>%{customdata[1]}<extra></extra>"),
    ))
    fig.add_vline(x=0, line_width=1.5, line_color="#8A8A8A")
    fig.update_layout(
        title=f"Validation ranking — {ranking.lower()}",
        paper_bgcolor="#0F0F0F", plot_bgcolor="#0F0F0F", font_color="#E0E0E0",
        xaxis_title="Mean Forward ATR − Baseline Mean ATR", yaxis_title=None,
        height=max(440, min(760, 34 * len(data) + 160)),
        margin=dict(l=24, r=24, t=60, b=40),
    )
    fig.update_xaxes(gridcolor="#2A2A2A")
    fig.update_yaxes(autorange="reversed")
    return fig


def research_label(row: pd.Series) -> str:
    labels: list[str] = []
    if bool(row.get("lehr_short_pressure", False)):
        labels.append("LEHR Short Pressure")
    if bool(row.get("lehr_long_pressure", False)):
        labels.append("LEHR Long Pressure")
    if bool(row.get("helr_event", False)):
        labels.append("HELR Event")
    return ", ".join(labels) if labels else "None"


def show_quality(report: object) -> None:
    values = report.as_dict()  # type: ignore[attr-defined]
    st.dataframe(pd.DataFrame({"Metric": values.keys(),
                               "Value": [str(v) for v in values.values()]}),
                 hide_index=True, use_container_width=True)


def show_current_state(derived: pd.DataFrame, timezone: str) -> None:
    usable = derived.dropna(subset=["effort_score", "result_score"])
    if usable.empty:
        st.warning("No usable state rows after the warm-up period.")
        return
    current = usable.iloc[-1]
    timestamp = pd.Timestamp(current["timestamp"])
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    timestamp = timestamp.tz_convert(timezone)
    st.caption(f"Latest completed state: {timestamp:%Y-%m-%d %H:%M %Z}")
    cols = st.columns(7)
    values = (
        ("Effort", number(current["effort_score"], 2, True)),
        ("Result", number(current["result_score"], 2, True)),
        ("Region", str(current["effort_result_region"])),
        ("Positioning", str(current["positioning_state"])),
        ("Strength", number(current["state_strength"], 2)),
        ("Velocity", number(current["state_velocity"], 2)),
        ("Research", research_label(current)),
    )
    for col, (label, value) in zip(cols, values):
        col.metric(label, value)
    if bool(current.get("near_state_boundary", False)):
        st.warning("Current observation is near a zero boundary; treat its region assignment as low confidence.")
