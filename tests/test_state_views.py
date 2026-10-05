from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.state_views import (
    boundary_label, build_timeline_frame, compute_recent_state_summary,
    compute_region_occupancy, compute_state_rarity, extract_positioning_transitions,
    extract_region_transitions, flag, match_current_validation_rows,
    prepare_state_frame, research_label,
)
from src.states import EFFORT_RESULT_REGIONS


@pytest.mark.parametrize("value,expected", [("False", False), ("TRUE", True), ("0", False), (1, True), (pd.NA, None), ("unknown", None)])
def test_nullable_string_flags(value, expected):
    assert flag(value) is expected


def test_object_numeric_sort_and_input_immutability(hosted_frame):
    frame = hosted_frame.iloc[::-1].copy()
    original = frame.copy(deep=True)
    prepared = prepare_state_frame(frame)
    assert prepared.timestamp.is_monotonic_increasing
    assert prepared.effort_score.dtype.kind == "f"
    assert len(build_timeline_frame(frame)) == 12
    pd.testing.assert_frame_equal(frame, original)


def test_invalid_scores_and_optional_columns(derived):
    minimal = derived.tail(4)[["timestamp", "effort_score", "result_score"]].copy()
    minimal.loc[minimal.index[0], "effort_score"] = np.inf
    prepared = prepare_state_frame(minimal)
    assert len(prepared) == 3
    assert boundary_label(prepared.iloc[-1]) == "Boundary unavailable"
    assert research_label(prepared.iloc[-1]) == "Unavailable"
    assert prepare_state_frame(pd.DataFrame()).empty
    assert compute_state_rarity(pd.DataFrame()) == {"n": 0}
    assert compute_recent_state_summary(pd.DataFrame()) == {"n": 0}


def test_window_occupancy_and_current(derived):
    occupancy = compute_region_occupancy(derived, history=250, recent_n=12)
    assert occupancy["Historical N"].eq(250).all()
    assert occupancy["Recent N"].eq(12).all()
    assert occupancy["Recent count"].sum() == 12
    assert occupancy["Historical %"].sum() == pytest.approx(100)
    assert occupancy["Recent %"].sum() == pytest.approx(100)
    assert occupancy["Current"].sum() == 1
    assert occupancy.loc[occupancy.Current, "Region"].iloc[0] == derived.iloc[-1].effort_result_region
    np.testing.assert_allclose(occupancy["Recent − historical pp"], occupancy["Recent %"]-occupancy["Historical %"])
    assert compute_region_occupancy(derived, None)["Historical N"].eq(len(prepare_state_frame(derived))).all()


def test_known_summary_transitions_and_deltas(derived):
    frame = derived.tail(5).copy()
    frame["effort_result_region"] = [EFFORT_RESULT_REGIONS[i] for i in (0, 0, 1, 1, 0)]
    frame["positioning_state"] = ["Short Covering", "Short Covering", "Short Covering", "Mixed / Low Conviction", "Mixed / Low Conviction"]
    summary = compute_recent_state_summary(frame)
    assert summary["dominant_region_count"] == 3
    assert summary["dominant_positioning"] == "Short Covering"
    assert summary["region_transitions"] == 2
    assert summary["positioning_transitions"] == 1
    assert summary["net_effort"] == pytest.approx(frame.iloc[-1].effort_score - frame.iloc[0].effort_score)
    assert summary["latest_result"] == pytest.approx(frame.iloc[-1].result_score - frame.iloc[-2].result_score)
    assert len(extract_region_transitions(frame)) == 2
    assert len(extract_positioning_transitions(frame)) == 1
    assert extract_region_transitions(frame).timestamp.is_monotonic_increasing


@pytest.mark.parametrize("break_type", ["missing_bar", "segment"])
def test_transitions_never_bridge_discontinuities(derived, break_type):
    frame = derived.tail(2).copy()
    frame["effort_result_region"] = list(EFFORT_RESULT_REGIONS[:2])
    if break_type == "missing_bar":
        frame.loc[frame.index[-1], "timestamp"] += pd.Timedelta(minutes=5)
    else:
        frame.loc[frame.index[-1], "segment_id"] += 1
    summary = compute_recent_state_summary(frame)
    assert summary["region_transitions"] == 0
    assert summary["gaps"] == 1
    assert np.isnan(summary["latest_effort"])
    assert np.isnan(summary["net_result"])


def test_single_state_and_dominant_tie(derived):
    frame = derived.tail(2).copy()
    frame["effort_result_region"] = list(EFFORT_RESULT_REGIONS[:2])
    assert "(tie)" in compute_recent_state_summary(frame)["dominant_region"]
    one = compute_recent_state_summary(frame.tail(1))
    assert one["comparable_steps"] == 0
    assert np.isnan(one["latest_result"])
    assert one["net_effort"] == 0


def test_percentiles_use_only_visible_history(derived):
    frame = derived.tail(5).copy()
    frame["effort_score"] = [100, 100, 0, 1, 1]
    frame["state_strength"] = [0, 1, 2, np.nan, 4]
    rarity = compute_state_rarity(frame, history=3)
    assert rarity["Effort percentile"] == 100
    assert compute_state_rarity(frame, None)["Effort percentile"] == 60
    assert rarity["Strength N"] == 2
    assert rarity["Strength percentile"] == 100


def validation_rows(region, positioning, qualities=("Usable research sample",)*3):
    return pd.DataFrame([
        {"Group Type": kind, "Group": group, "Positioning State": pos, "Horizon": "5",
         "Sample Quality": quality, "Non-Overlapping N": "100", "Mean Forward ATR": "0.15",
         "Median Forward ATR": "0.1", "Positive Rate": "0.52", "Mean ATR Difference vs Baseline": "0.02",
         "Difference vs Baseline ATR 95% CI Low": "-0.1", "Difference vs Baseline ATR 95% CI High": "0.3",
         "Tail-Driven Result Warning": "False"}
        for kind, group, pos, quality in zip(
            ("Region × Positioning State", "Positioning State", "Effort-Result Region"),
            (region, "All Regions", region), (positioning, positioning, "All"), qualities)
    ])


@pytest.mark.parametrize("case,scope,quality", [
    ("joint", "Region × Positioning State", "Usable research sample"),
    ("positioning", "Positioning State", "Usable research sample"),
    ("region", "Effort-Result Region", "Usable research sample"),
    ("insufficient", "Region × Positioning State", "Insufficient sample"),
    ("exploratory", "Region × Positioning State", "Exploratory"),
    ("fallback", "Positioning State", "Usable research sample"),
])
def test_validation_matching_priority_quality(case, scope, quality, derived):
    current = derived.iloc[-1]
    rows = validation_rows(current.effort_result_region, current.positioning_state)
    if case == "positioning":
        rows = rows.iloc[1:]
    elif case == "region":
        rows = rows.iloc[2:]
    elif case == "insufficient":
        rows["Sample Quality"] = quality
    elif case == "exploratory":
        rows.loc[0, "Sample Quality"] = quality
    elif case == "fallback":
        rows.loc[0, "Sample Quality"] = "Insufficient sample"
    original = rows.copy(deep=True)
    matched = match_current_validation_rows(current, rows)
    assert matched.iloc[0]["Matched scope"] == scope
    assert matched.iloc[0]["Sample Quality"] == quality
    assert bool(matched.iloc[0]["Adequate sample"]) == (quality != "Insufficient sample")
    assert matched.iloc[0]["Mean Forward ATR"] == .15
    pd.testing.assert_frame_equal(rows, original)


def test_validation_missing_and_per_horizon_matching(derived):
    current = derived.iloc[-1]
    assert match_current_validation_rows(current, pd.DataFrame()).empty
    rows = validation_rows("unrelated", "unrelated")
    assert match_current_validation_rows(current, rows).empty
    rows = validation_rows(current.effort_result_region, current.positioning_state)
    next_h = rows.iloc[1:].copy()
    next_h["Horizon"] = 20
    matched = match_current_validation_rows(current, pd.concat([rows, next_h]))
    assert list(matched.Horizon) == [5, 20]
    assert list(matched["Matched scope"]) == ["Region × Positioning State", "Positioning State"]
