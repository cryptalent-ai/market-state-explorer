"""Active v1.3.3 semantics, hosted runtime and protected-source regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.charts_v133 import (
    DISCRETE_STATE_NOTE, effort_result_time_figure, snapshot_cloud_figure, state_map_figure,
)
from src.state_views import build_timeline_frame
from src.validation import calculate_forward_outcomes
from tests.test_visual_v13 import hosted_page

ROOT = Path(__file__).parents[1]


def sampled_traces(figure):
    return [t for t in figure.data if t.meta == "recent-observations"]


def assert_discrete_cloud(figure, expected):
    assert all("lines" not in (t.mode or "") for t in figure.data if hasattr(t, "mode"))
    assert all("Recent path" != t.name for t in figure.data)
    traces = sampled_traces(figure)
    assert [v for t in traces for v in t.x] == expected.effort_score.tolist()
    assert [v for t in traces for v in t.y] == expected.result_score.tolist()
    if len(expected):
        current = next(t for t in traces if t.name == "Current")
        assert current.marker.symbol == "star" and current.marker.color == "#FFD54F"
        assert expected.iloc[-1].effort_result_region in figure.layout.title.text
    if len(expected) > 1:
        previous = next(t for t in traces if t.name == "Previous")
        assert previous.marker.symbol == "circle-open"
        assert list(previous.x) == [expected.iloc[-2].effort_score]
    arrows = [a for a in figure.layout.annotations if a.showarrow]
    if len(expected) > 1:
        assert len(arrows) == 1
        last = arrows[0]
        assert last.name == "Latest move"
        assert (last.ax, last.ay) == (expected.iloc[-2].effort_score, expected.iloc[-2].result_score)
        assert (last.x, last.y) == (expected.iloc[-1].effort_score, expected.iloc[-1].result_score)
        assert (last.axref, last.ayref, last.xref, last.yref) == ("x", "y", "x", "y")
    else:
        assert not arrows
    assert len(figure.layout.shapes) == 2
    assert len([a for a in figure.layout.annotations if not a.showarrow]) == 4


@pytest.mark.parametrize("mode", ["Density + recent", "Recent only", "Full scatter"])
@pytest.mark.parametrize("n", [1, 2, 12, 30])
def test_state_map_discrete_observations_markers_latest_vector(hosted_frame, mode, n):
    original = hosted_frame.copy(deep=True)
    figure = state_map_figure(hosted_frame.iloc[::-1], recent_points=n, mode=mode)
    assert_discrete_cloud(figure, build_timeline_frame(hosted_frame, n))
    assert json.loads(figure.to_json())["data"]
    pd.testing.assert_frame_equal(hosted_frame, original, check_exact=True)


def test_density_history_preserved_and_recency_size_brightness(derived):
    figure = state_map_figure(derived, history=100, recent_points=12)
    history = build_timeline_frame(derived, 100)
    density, older, previous, current, _ = figure.data
    assert density.type == "histogram2d"
    np.testing.assert_array_equal(density.x, history.effort_score)
    np.testing.assert_array_equal(density.y, history.result_score)
    assert density.nbinsx == density.nbinsy == 32
    assert list(older.marker.size) == sorted(older.marker.size)
    assert older.marker.size[0] < older.marker.size[-1] < previous.marker.size < current.marker.size
    assert older.marker.colorscale[0][1] == "#526575"
    assert older.marker.colorscale[-1][1] == "#DAE8F4"
    assert list(older.marker.color) == list(range(10))
    assert [t.name for t in figure.data[1:]] == ["Older recent states", "Previous", "Current", "Latest move"]


def test_snapshot_cloud_no_density_or_polyline(hosted_frame):
    figure = snapshot_cloud_figure(hosted_frame.iloc[::-1])
    assert_discrete_cloud(figure, build_timeline_frame(hosted_frame))
    assert figure.layout.title.text.startswith("2D Snapshot Cloud")
    assert all(t.type == "scatter" for t in figure.data)
    assert json.loads(figure.to_json())["layout"]


@pytest.mark.parametrize("reason", ["gap", "segment", "zero displacement"])
def test_latest_vector_never_bridges_discontinuity_or_invents_direction(derived, reason):
    frame = derived.tail(12).copy().reset_index(drop=True)
    if reason == "gap":
        frame.loc[11, "timestamp"] += pd.Timedelta(minutes=5)
    elif reason == "segment":
        frame.loc[11, "segment_id"] = 99
    else:
        frame.loc[11, ["effort_score", "result_score"]] = frame.loc[10, ["effort_score", "result_score"]].values
    figure = snapshot_cloud_figure(frame)
    assert not any(a.showarrow for a in figure.layout.annotations)
    assert not any(t.name == "Latest move" for t in figure.data)
    assert sum(len(t.x) for t in sampled_traces(figure)) == 12


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Taipei", "America/New_York"])
def test_time_panels_actual_timestamp_exact_scores_zero_and_latest(hosted_frame, timezone):
    original = hosted_frame.copy(deep=True)
    figure = effort_result_time_figure(hosted_frame.iloc[::-1], timezone=timezone)
    recent = build_timeline_frame(hosted_frame)
    observations = [t for t in figure.data if t.meta == "time-observations"]
    assert [t.name for t in observations] == ["Effort", "Result"]
    for trace, column in zip(observations, ["effort_score", "result_score"]):
        assert list(pd.to_datetime(trace.x, utc=True)) == recent.timestamp.tolist()
        assert list(trace.y) == recent[column].tolist()
        assert trace.x[0] < trace.x[-1]
    assert figure.layout.xaxis.type == figure.layout.xaxis2.type == "date"
    assert figure.layout.xaxis.matches == "x2"
    assert {s.yref for s in figure.layout.shapes} == {"y", "y2"}
    assert all(s.y0 == s.y1 == 0 for s in figure.layout.shapes)
    for name, offset, symbol in (("Current", -1, "star"), ("Previous", -2, "circle-open")):
        markers = [t for t in figure.data if t.name == name]
        assert len(markers) == 2 and all(t.marker.symbol == symbol for t in markers)
        assert all(pd.Timestamp(t.x[0]) == recent.iloc[offset].timestamp for t in markers)
    assert json.loads(figure.to_json())["data"]
    pd.testing.assert_frame_equal(hosted_frame, original, check_exact=True)


@pytest.mark.parametrize("reason", ["gap", "segment"])
def test_time_guides_break_at_discontinuities(derived, reason):
    frame = derived.tail(4).copy().reset_index(drop=True)
    if reason == "gap":
        frame.loc[2:, "timestamp"] += pd.Timedelta(minutes=5)
    else:
        frame.loc[2:, "segment_id"] = 99
    figure = effort_result_time_figure(frame)
    for trace in figure.data:
        if trace.meta == "time-guide":
            assert trace.x[2] is None and trace.y[2] is None
            assert trace.connectgaps is False
        elif trace.meta == "time-observations":
            assert len(trace.x) == len(trace.y) == 4


@pytest.mark.parametrize("chart", [state_map_figure, snapshot_cloud_figure, effort_result_time_figure])
def test_empty_new_charts_serialize(chart):
    assert json.loads(chart(pd.DataFrame()).to_json())["layout"]


@pytest.mark.parametrize("page", ["State Map", "Trajectory"])
def test_active_ui_uses_only_new_charts_and_collapsed_cloud(monkeypatch, hosted_frame, page):
    import src.web_app_v13 as ui
    captured = []
    original_plot = ui._plot

    def capture(figure):
        captured.append(figure)
        original_plot(figure)

    monkeypatch.setattr(ui, "_plot", capture)
    # Legacy path renderers must not be reachable from the active page.
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy polyline renderer called")
    monkeypatch.setattr(ui.charts_v12, "state_map_figure", forbidden)
    monkeypatch.setattr(ui.charts_v12, "trajectory_figure", forbidden)
    app = AppTest.from_function(hosted_page, args=(hosted_frame, pd.DataFrame(), page)).run(timeout=20)
    assert not app.exception
    assert all(not e.proto.expanded for e in app.expander)
    assert not any(t.name == "Recent path" for f in captured for t in f.data)
    if page == "Trajectory":
        assert captured[0].layout.title.text.startswith("Effort / Result over Time")
        assert app.expander[0].label == "Advanced: 2D Snapshot Cloud"
        assert captured[-1].layout.title.text.startswith("2D Snapshot Cloud")
        assert app.subheader[0].value == "Effort / Result over Time"
        html = "\n".join(m.value for m in app.markdown)
        assert "Latest ΔEffort" in html and "Latest ΔResult" in html
    else:
        assert captured[-1].layout.title.text.startswith("Effort–Result State Map")
    assert any(DISCRETE_STATE_NOTE in c.value for c in app.caption)


def test_visual_calls_preserve_quantitative_values_and_forward_outcomes(derived):
    original = derived.copy(deep=True)
    before = {h: calculate_forward_outcomes(derived, h) for h in [5, 10, 20]}
    for chart in (state_map_figure, snapshot_cloud_figure, effort_result_time_figure):
        chart(derived)
    pd.testing.assert_frame_equal(original, derived, check_exact=True)
    for h in before:
        pd.testing.assert_frame_equal(before[h], calculate_forward_outcomes(derived, h), check_exact=True)


def test_visual_as_of_prefix_no_lookahead(derived):
    before = derived.iloc[:380].copy()
    changed = derived.copy()
    changed.loc[380:, ["effort_score", "result_score"]] = 999999
    as_of = before.iloc[-1].timestamp
    for chart in (state_map_figure, snapshot_cloud_figure, effort_result_time_figure):
        assert chart(before).to_json() == chart(changed[changed.timestamp.le(as_of)]).to_json()


def test_main_protected_files_and_original_golden_fixtures_unchanged():
    manifest = json.loads((ROOT / "tests/fixtures/v133_visual_scope_sha256.json").read_text("utf-8"))
    assert manifest["base_commit"] == "ad2079b6b813ce208c041342bccd73ee4c2a5a90"
    assert set(manifest["authorized_ui_sha256"]) == {"src/web_app_v13.py"}
    protected = manifest["protected_sha256"]
    assert len(protected) == 38
    assert {"src/validation.py", "src/relay.py", "src/oi_alignment.py", "src/state_views.py", "src/cache.py", "scripts/publish_live_relay.py"} <= protected.keys()
    for path, expected in protected.items():
        assert hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected, path
