"""Concise deterministic summaries for the visual state views.

These helpers describe geometry only. They do not generate trade signals or change
any model calculation.
"""
from __future__ import annotations

import pandas as pd


def _valid(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    return frame.dropna(subset=["effort_score", "result_score"]).tail(max(2, int(lookback))).copy()


def state_map_insight(frame: pd.DataFrame, *, lookback: int = 12) -> str:
    data = _valid(frame, lookback)
    if data.empty:
        return "No usable state observations are available yet."
    current = data.iloc[-1]
    region = str(current.get("effort_result_region", "Unclassified"))
    effort = float(current["effort_score"])
    result = float(current["result_score"])
    boundary = bool(current.get("near_state_boundary", False))
    sentence = f"Current state: {region} · Effort {effort:+.2f} · Result {result:+.2f}."
    if boundary:
        sentence += " The observation is near a zero boundary, so the region label should be treated as low confidence."
    return sentence


def trajectory_insight(frame: pd.DataFrame, *, lookback: int = 12) -> str:
    data = _valid(frame, lookback)
    if len(data) < 2:
        return "At least two usable states are required to describe recent movement."
    start = data.iloc[0]
    current = data.iloc[-1]
    de = float(current["effort_score"] - start["effort_score"])
    dr = float(current["result_score"] - start["result_score"])
    latest_de = float(current["effort_score"] - data.iloc[-2]["effort_score"])
    latest_dr = float(current["result_score"] - data.iloc[-2]["result_score"])

    def direction(value: float, label: str) -> str:
        if abs(value) < 0.15:
            return f"{label} roughly flat"
        return f"{label} {'higher' if value > 0 else 'lower'}"

    return (
        f"Across the last {len(data)} valid states: {direction(de, 'Effort')}, "
        f"{direction(dr, 'Result')} (ΔE {de:+.2f}, ΔR {dr:+.2f}). "
        f"Latest move: ΔE {latest_de:+.2f}, ΔR {latest_dr:+.2f}."
    )
