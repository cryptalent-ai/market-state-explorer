from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.charts_v12 import state_map_figure, trajectory_figure
from src.charts_v13 import small_multiples_figure, state_matrix_figure, timeline_ribbon_figure
from src.state_views import prepare_state_frame
from tests.test_state_views import validation_rows


@pytest.mark.parametrize("chart", ["matrix", "ribbon", "multiples", "density", "recent", "scatter", "phase"])
def test_hosted_dtype_figures_serialize(hosted_frame, chart):
    original = hosted_frame.copy(deep=True)
    prepared = prepare_state_frame(hosted_frame)
    figures = {
        "matrix": lambda: state_matrix_figure(hosted_frame),
        "ribbon": lambda: timeline_ribbon_figure(hosted_frame),
        "multiples": lambda: small_multiples_figure(hosted_frame),
        "density": lambda: state_map_figure(prepared, mode="Density + recent"),
        "recent": lambda: state_map_figure(prepared, mode="Recent only"),
        "scatter": lambda: state_map_figure(prepared, mode="Full scatter", color_by="Positioning"),
        "phase": lambda: trajectory_figure(prepared, trail_length=12),
    }
    payload = json.loads(figures[chart]().to_json())
    assert "layout" in payload
    if chart != "matrix":
        assert payload["data"]
    pd.testing.assert_frame_equal(hosted_frame, original)


def test_matrix_full_labels_and_current_marker(derived):
    figure = state_matrix_figure(derived)
    labels = [a.text for a in figure.layout.annotations]
    assert len(labels) == 4
    assert all("History:" in label and "Recent 12:" in label for label in labels)
    assert sum("CURRENT" in label for label in labels) == 1
    assert any(derived.iloc[-1].effort_result_region in label and "CURRENT" in label for label in labels)


def test_ribbon_chronological_rightmost_and_hover(derived):
    figure = timeline_ribbon_figure(derived.iloc[::-1])
    ribbon = figure.data[0]
    assert list(ribbon.x) == list(range(12))
    assert len(ribbon.y) == 4
    assert derived.iloc[-1].positioning_state in ribbon.customdata[0][-1]
    assert str(derived.iloc[-1].timestamp.year) in ribbon.customdata[0][-1]
    assert figure.layout.shapes[-1].x1 == 11.5
    assert "LATEST" in figure.layout.annotations[-1].text


def test_small_multiples_shared_axes_and_current(derived):
    figure = small_multiples_figure(derived)
    assert len(figure.data) == 8
    assert len(figure.layout.shapes) == 2
    for trace in figure.data[1::2]:
        assert trace.marker.symbol == "star"
        assert len(trace.x) == 1
    assert figure.layout.xaxis.matches == "x4"


@pytest.mark.parametrize("chart", [state_matrix_figure, timeline_ribbon_figure, small_multiples_figure])
def test_empty_chart_serialization(chart):
    assert json.loads(chart(pd.DataFrame()).to_json())["layout"]


def hosted_page(frame, validation, page):
    import streamlit as st
    from src.config import ModelConfig
    from src.state_views import prepare_state_frame
    from src.web_app_v13 import STYLE, render_dashboard, render_state_map, render_trajectory
    st.markdown(STYLE, unsafe_allow_html=True)
    prepared = prepare_state_frame(frame)
    if page == "Dashboard":
        render_dashboard(prepared, None, None, "Hosted dtype fixture", ModelConfig(), 500, 12, validation)
    elif page == "State Map":
        render_state_map(prepared, ModelConfig(), 500, 12)
    else:
        render_trajectory(prepared, ModelConfig(), 12)


@pytest.mark.parametrize("page", ["Dashboard", "State Map", "Trajectory"])
def test_hosted_streamlit_primary_pages(hosted_frame, page):
    current = hosted_frame.iloc[-1]
    validation = validation_rows(current.effort_result_region, current.positioning_state)
    app = AppTest.from_function(hosted_page, args=(hosted_frame, validation, page)).run(timeout=20)
    assert not app.exception
    text = "\n".join(m.value for m in app.markdown)
    if page != "Trajectory":
        assert current.effort_result_region in text
        assert current.positioning_state in text
    if page == "Dashboard":
        assert any(m.value.startswith("Recent 5 valid states") for m in app.subheader)
        assert "No warning" in text  # string 'False' is not a tail warning
        assert "Difference vs Baseline 95% CI (ATR)" in text
    else:
        assert all(e.proto.expanded is False for e in app.expander)
    assert len(app.get("plotly_chart")) >= 2


@pytest.mark.parametrize("page", ["Dashboard", "State Map", "Trajectory", "Validation", "Data Quality", "Methodology"])
def test_full_entry_point_navigation_smoke(monkeypatch, derived, page):
    import src.web_app_v13 as ui
    from src.relay import RelayMetadata
    meta = RelayMetadata("Official Binance relay", "2026-10-05T12:05:00Z", "2026-10-05T12:00:00Z", len(derived), 1., 0, 60., True)
    monkeypatch.setattr(ui, "_load_selected_dataset", lambda *a: (derived, None, meta, None, "Relay"))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=20)
    app.sidebar.radio[0].set_value(page).run(timeout=20)
    assert not app.exception
    if page == "Dashboard":
        assert any("Relay active" in s.value for s in app.success)


def test_delayed_archive_warning_is_not_live(monkeypatch, derived):
    import src.web_app_v13 as ui
    meta = SimpleNamespace(source="Official Binance delayed hosted fallback", completed_through_utc="2026-10-02 00:00 UTC", oi_coverage=1.)
    monkeypatch.setattr(ui, "_load_selected_dataset", lambda *a: (derived, None, meta, None, "Delayed archive"))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=20)
    assert not app.exception
    assert any("NOT the current market state" in s.value for s in app.warning)
