"""Final UI polish: wording and layout cannot change audited inputs/outcomes."""
from __future__ import annotations

from html import escape

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.state_views import compute_recent_state_summary, prepare_state_frame, switching_label
from tests.test_state_views import validation_rows
from tests.test_visual_v13 import hosted_page


@pytest.mark.parametrize("changes,steps,label", [
    (0, 0, "Unavailable"), (0, 1, "Mostly stable"),
    (1, 1, "Frequent switching"), (1, 3, "Mostly stable"),
    (2, 3, "Frequent switching"), (3, 9, "Mostly stable"),
    (4, 9, "Moderate switching"), (5, 9, "Moderate switching"),
    (6, 9, "Frequent switching"), (9, 9, "Frequent switching"),
    (3, 11, "Mostly stable"), (4, 11, "Moderate switching"),
    (7, 11, "Moderate switching"), (8, 11, "Frequent switching"),
])
def test_switching_display_labels(changes, steps, label):
    assert switching_label(changes, steps) == label


@pytest.mark.parametrize("page", ["Dashboard", "Trajectory"])
def test_polish_cards_hosted_dtypes_preserve_data(hosted_frame, page):
    original = hosted_frame.copy(deep=True)
    prepared = prepare_state_frame(hosted_frame)
    before = compute_recent_state_summary(prepared, 12)
    current = prepared.iloc[-1]
    validation = validation_rows(current.effort_result_region, current.positioning_state)
    app = AppTest.from_function(hosted_page, args=(hosted_frame, validation, page)).run(timeout=20)
    assert not app.exception
    html = "\n".join(m.value for m in app.markdown)
    assert switching_label(before["region_transitions"], before["comparable_steps"]) in html
    assert f"Region: {before['region_transitions']}" in html
    assert escape(current.effort_result_region) in html
    if page == "Dashboard":
        assert "LATEST VALID STATE · MARKET-BAR TIMESTAMP" in html
        assert "source / publication freshness is shown separately above" in html
    else:
        overview = next(m.value for m in app.markdown if 'class="v13-card current v13-overview"' in m.value)
        assert all(label in overview for label in (
            "Dominant recent Region", "Dominant recent Positioning",
            "Switching intensity", "Current Region", "Zero-boundary status",
        ))
        assert escape(before["dominant_region"]) in overview
        assert escape(before["dominant_positioning"]) in overview
        assert before["boundary"] in overview
        assert all(e.proto.expanded is False for e in app.expander)
        assert app.markdown[1].value == overview  # first content after style
    pd.testing.assert_frame_equal(hosted_frame, original, check_exact=True)
    assert compute_recent_state_summary(prepared, 12) == before


def test_trajectory_legend_uses_only_chronological_valid_recent_window(hosted_frame):
    from src.charts_v13 import REGION_COLORS
    from src.charts_v12 import POSITIONING_COLORS
    frame = hosted_frame.copy(deep=True)
    regions, positioning = list(REGION_COLORS), list(POSITIONING_COLORS)
    frame["effort_result_region"] = regions[0]
    frame["positioning_state"] = positioning[0]
    frame.loc[frame.index[-12:], "effort_result_region"] = regions[1]
    frame.loc[frame.index[-12:], "positioning_state"] = positioning[1]
    # A latest invalid row must not affect legend categories or window length.
    invalid = frame.iloc[-1:].copy()
    invalid["timestamp"] = str(pd.Timestamp("2099-01-01", tz="UTC"))
    invalid["effort_score"] = "not numeric"
    invalid["effort_result_region"] = regions[2]
    invalid["positioning_state"] = positioning[2]
    frame = pd.concat([frame, invalid], ignore_index=True).iloc[::-1]
    app = AppTest.from_function(hosted_page, args=(frame, pd.DataFrame(), "Trajectory")).run(timeout=20)
    assert not app.exception
    legends = [m.value for m in app.markdown if 'class="v13-legend"' in m.value]
    assert len(legends) == 2
    assert escape(regions[1]) in legends[0]
    assert all(escape(label) not in legends[0] for label in regions if label != regions[1])
    assert escape(positioning[1]) in legends[1]
    assert all(escape(label) not in legends[1] for label in positioning if label != positioning[1])


def test_trajectory_unknown_categories_have_neutral_legend(hosted_frame):
    frame = hosted_frame.copy()
    frame["effort_result_region"] = None
    frame["positioning_state"] = None
    app = AppTest.from_function(hosted_page, args=(frame, pd.DataFrame(), "Trajectory")).run(timeout=20)
    assert not app.exception
    legends = [m.value for m in app.markdown if 'class="v13-legend"' in m.value]
    assert len(legends) == 2
    assert all("Unavailable" in text and "#303438" in text for text in legends)


def isolated_overview(frame):
    from src.web_app_v13 import render_trajectory_summary
    render_trajectory_summary(frame, 12)


def test_empty_overview_is_unavailable_not_stable():
    app = AppTest.from_function(isolated_overview, args=(pd.DataFrame(),)).run()
    assert not app.exception
    assert "No valid states" in app.info[0].value


def test_discontinuous_overview_does_not_invent_switches(derived):
    frame = derived.tail(3).copy()
    frame["timestamp"] = pd.date_range("2025-01-01", periods=3, freq="10min", tz="UTC")
    app = AppTest.from_function(isolated_overview, args=(frame,)).run()
    assert not app.exception
    html = app.markdown[0].value
    assert "Region: 0 / 0 comparable steps; Positioning: Unavailable (0 / 0)" in html
    assert "2 discontinuities excluded" in html


def source_and_state_clocks(frame, meta):
    from src.web_app_v13 import _source_status, render_current_state
    _source_status(meta, "Relay", None)
    render_current_state(frame, "UTC")


def test_publication_freshness_separate_from_observation_clock(derived):
    from src.relay import RelayMetadata
    from src.web_app import _freshness_text
    meta = RelayMetadata("Official Binance relay", "2026-10-05T12:05:00Z", "2026-10-05T12:00:00Z", len(derived), 1., 0, 60., True)
    app = AppTest.from_function(source_and_state_clocks, args=(derived, meta)).run()
    assert not app.exception
    assert "RELAY PUBLICATION FRESHNESS" in app.success[0].value
    assert _freshness_text(meta) in app.success[0].value
    assert meta.updated_at_utc in app.caption[0].value
    assert meta.completed_through_utc in app.caption[0].value
    observation = next(m.value for m in app.markdown if 'class="v13-observation"' in m.value)
    assert "LATEST VALID STATE · MARKET-BAR TIMESTAMP" in observation
    assert "2025-01-02" in observation
    assert meta.updated_at_utc not in observation
    assert meta.age_seconds == 60. and meta.fresh is True
