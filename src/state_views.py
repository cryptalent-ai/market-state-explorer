"""Read-only presentation transforms. Never classify or recalculate model states.

Windows are chronological valid, already-derived states (not elapsed bars).
Percentiles use the selected visible history, including its latest observation.
Transitions/deltas never bridge missing bars or model segment boundaries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data_io import parse_timestamp
from .states import EFFORT_RESULT_REGIONS

NUMERIC_COLUMNS = (
    "effort_score", "result_score", "state_strength", "state_velocity",
    "open", "high", "low", "close", "volume", "delta", "delta_ratio",
    "oi", "oi_log_change", "bar_direction",
)
EVENT_COLUMNS = ("lehr_short_pressure", "lehr_long_pressure", "helr_event")
ADEQUATE_QUALITIES = {"Usable research sample", "Exploratory"}


def switching_label(transitions: int, comparable_steps: int) -> str:
    """UI wording only, from existing counts; never a model/validation signal.

    At most one third switching is mostly stable; at least two thirds is
    frequent. No comparable steps means unavailable, not stable.
    Integer comparisons keep the descriptive endpoints exact.
    """
    if comparable_steps <= 0:
        return "Unavailable"
    if 3 * transitions <= comparable_steps:
        return "Mostly stable"
    if 3 * transitions >= 2 * comparable_steps:
        return "Frequent switching"
    return "Moderate switching"


def flag(value) -> bool | None:
    """Parse nullable / CSV flags without treating the string 'False' as True."""
    if pd.isna(value):
        return None
    if isinstance(value, str):
        return {"true": True, "false": False, "1": True, "0": False}.get(value.strip().lower())
    if value in (True, 1):
        return True
    if value in (False, 0):
        return False
    return None


def prepare_state_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce display numbers on a copy; preserve audited categorical values."""
    result = frame.copy(deep=True)
    if "timestamp" not in result:
        result["timestamp"] = pd.NaT
    result["timestamp"] = parse_timestamp(result["timestamp"])
    for column in NUMERIC_COLUMNS:
        result[column] = pd.to_numeric(result.get(column, pd.Series(np.nan, index=result.index)), errors="coerce").replace([np.inf, -np.inf], np.nan)
    for column in ("effort_result_region", "positioning_state"):
        if column not in result:
            result[column] = "Unavailable"
        result[column] = result[column].fillna("Unavailable").astype(str)
    for column in (*EVENT_COLUMNS, "near_state_boundary"):
        result[column] = result.get(column, pd.Series(None, index=result.index, dtype=object)).map(flag)
    return result.dropna(subset=["timestamp", "effort_score", "result_score"]).sort_values("timestamp", kind="stable").reset_index(drop=True)


def build_timeline_frame(frame: pd.DataFrame, recent_n: int = 12) -> pd.DataFrame:
    return prepare_state_frame(frame).tail(max(0, recent_n)).copy()


def _history(frame: pd.DataFrame, history: int | None) -> pd.DataFrame:
    prepared = prepare_state_frame(frame)
    return prepared if history is None else prepared.tail(max(0, history))


def research_label(row: pd.Series) -> str:
    names = ("LEHR Short", "LEHR Long", "HELR")
    active = [name for name, column in zip(names, EVENT_COLUMNS) if flag(row.get(column)) is True]
    if active:
        return " / ".join(active)
    return "None" if all(flag(row.get(c)) is False for c in EVENT_COLUMNS) else "Unavailable"


def boundary_label(row: pd.Series) -> str:
    value = flag(row.get("near_state_boundary"))
    return {True: "Near zero boundary", False: "Not near zero boundary", None: "Boundary unavailable"}[value]


def compute_region_occupancy(frame: pd.DataFrame, history: int | None = 500, recent_n: int = 12) -> pd.DataFrame:
    historical, recent = _history(frame, history), build_timeline_frame(frame, recent_n)
    current = recent.iloc[-1]["effort_result_region"] if len(recent) else None
    rows = []
    for region in EFFORT_RESULT_REGIONS:
        h = int(historical["effort_result_region"].eq(region).sum())
        r = int(recent["effort_result_region"].eq(region).sum())
        hp = 100 * h / len(historical) if len(historical) else np.nan
        rp = 100 * r / len(recent) if len(recent) else np.nan
        rows.append({"Region": region, "Historical N": len(historical), "Historical count": h,
                     "Historical %": hp, "Recent N": len(recent), "Recent count": r,
                     "Recent %": rp, "Recent − historical pp": rp - hp, "Current": region == current})
    return pd.DataFrame(rows)


def _adjacent(frame: pd.DataFrame) -> pd.Series:
    valid = frame["timestamp"].diff().eq(pd.Timedelta(minutes=5))
    if "segment_id" in frame:
        valid &= frame["segment_id"].eq(frame["segment_id"].shift())
    return valid.fillna(False)


def _transitions(frame: pd.DataFrame, recent_n: int, column: str) -> pd.DataFrame:
    recent = build_timeline_frame(frame, recent_n)
    previous = recent[column].shift()
    selected = recent[_adjacent(recent) & recent[column].ne(previous)].copy()
    selected["From"] = previous.loc[selected.index]
    selected["To"] = selected[column]
    return selected[["timestamp", "From", "To", "effort_score", "result_score"]].reset_index(drop=True)


def extract_region_transitions(frame: pd.DataFrame, recent_n: int = 12) -> pd.DataFrame:
    return _transitions(frame, recent_n, "effort_result_region")


def extract_positioning_transitions(frame: pd.DataFrame, recent_n: int = 12) -> pd.DataFrame:
    return _transitions(frame, recent_n, "positioning_state")


def _dominant(values: pd.Series) -> tuple[str, int]:
    counts = values.value_counts()
    if counts.empty:
        return "Unavailable", 0
    largest = int(counts.iloc[0])
    names = sorted(counts[counts.eq(largest)].index)
    return (" / ".join(names) + (" (tie)" if len(names) > 1 else ""), largest)


def compute_recent_state_summary(frame: pd.DataFrame, recent_n: int = 12) -> dict:
    recent = build_timeline_frame(frame, recent_n)
    result = {"n": len(recent)}
    if recent.empty:
        return result
    region, region_count = _dominant(recent["effort_result_region"])
    positioning, positioning_count = _dominant(recent["positioning_state"])
    adjacent = _adjacent(recent)
    gaps = int((~adjacent.iloc[1:]).sum())
    result.update(dominant_region=region, dominant_region_count=region_count,
                  dominant_positioning=positioning, dominant_positioning_count=positioning_count,
                  region_transitions=len(extract_region_transitions(recent, recent_n)),
                  positioning_transitions=len(extract_positioning_transitions(recent, recent_n)),
                  comparable_steps=int(adjacent.sum()), gaps=gaps, boundary=boundary_label(recent.iloc[-1]))
    for label, column in (("effort", "effort_score"), ("result", "result_score")):
        result[f"net_{label}"] = float(recent.iloc[-1][column] - recent.iloc[0][column]) if gaps == 0 else np.nan
        result[f"latest_{label}"] = float(recent.iloc[-1][column] - recent.iloc[-2][column]) if len(recent) > 1 and adjacent.iloc[-1] else np.nan
    return result


def compute_state_rarity(frame: pd.DataFrame, history: int | None = 500) -> dict:
    selected = _history(frame, history)
    if selected.empty:
        return {"n": 0}
    current = selected.iloc[-1]
    output = {"n": len(selected)}
    for name, column in (("Effort", "effort_score"), ("Result", "result_score"), ("Strength", "state_strength")):
        values = selected[column].dropna()
        output[f"{name} percentile"] = 100 * values.le(current[column]).mean() if len(values) and pd.notna(current[column]) else np.nan
        output[f"{name} N"] = len(values)
    counts = selected["effort_result_region"].value_counts()
    if current["effort_result_region"] not in EFFORT_RESULT_REGIONS:
        output["Current region frequency %"] = np.nan
        output["Frequency description"] = "Region unavailable"
        return output
    count = int(counts.get(current["effort_result_region"], 0))
    output["Current region frequency %"] = 100 * count / len(selected)
    all_counts = [int(counts.get(region, 0)) for region in EFFORT_RESULT_REGIONS]
    output["Frequency description"] = "Equal frequency" if len(set(all_counts)) == 1 else "Most frequent region" if count == max(all_counts) else "Least frequent region" if count == min(all_counts) else "Intermediate frequency region"
    return output


def match_current_validation_rows(current_row: pd.Series, validation_frame: pd.DataFrame) -> pd.DataFrame:
    """Match per horizon, preferring adequate joint then marginal samples.

    Reuse published Sample Quality labels; do not calculate new quality cutoffs.
    Insufficient matches remain visible, but never become adequate evidence.
    """
    required = {"Group Type", "Group", "Positioning State", "Horizon", "Sample Quality"}
    if not required.issubset(validation_frame.columns):
        return pd.DataFrame()
    data = validation_frame.copy(deep=True)
    text_columns = required - {"Horizon", "Sample Quality"}
    for column in data.columns.difference(list(text_columns) + ["Sample Quality"]):
        if column not in ("Mean vs Median Divergence Warning", "Tail-Driven Result Warning"):
            data[column] = pd.to_numeric(data[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    region, positioning = current_row.get("effort_result_region"), current_row.get("positioning_state")
    masks = [
        data["Group Type"].eq("Region × Positioning State") & data["Group"].eq(region) & data["Positioning State"].eq(positioning),
        data["Group Type"].eq("Positioning State") & data["Positioning State"].eq(positioning),
        data["Group Type"].eq("Effort-Result Region") & data["Group"].eq(region),
    ]
    rows = []
    for horizon in sorted(data["Horizon"].dropna().unique()):
        candidates = [data[mask & data["Horizon"].eq(horizon)] for mask in masks]
        matches = [candidate.iloc[0] for candidate in candidates if len(candidate)]
        if not matches:
            continue
        row = next((r for r in matches if r["Sample Quality"] in ADEQUATE_QUALITIES), matches[0]).copy()
        row["Matched scope"] = row["Group Type"]
        row["Adequate sample"] = row["Sample Quality"] in ADEQUATE_QUALITIES
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)
