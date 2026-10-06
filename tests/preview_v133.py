"""Offline visual-review harness, using the real page/chart renderers.

Run from repository root: python -m streamlit run tests/preview_v133.py
The fixture is deterministic, not a live market or freshness acceptance.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import streamlit as st

from src.charts_v133 import DISCRETE_STATE_NOTE, snapshot_cloud_figure, state_map_figure
from src.config import ModelConfig
from src.data_io import prepare_market_data
from src.features import build_derived_features
from src.state_views import prepare_state_frame
from src.web_app_v13 import STYLE, _plot, render_trajectory
from tests.conftest import fixed_market_frame

st.set_page_config(page_title="v1.3.3 visual acceptance preview", layout="wide")
st.markdown(STYLE, unsafe_allow_html=True)
st.caption("v1.3.3 preview · deterministic audited test fixture · NOT live market data")
page = st.sidebar.radio("Preview view", ("Advanced State Map", "Trajectory default", "2D Snapshot Cloud"))
frame = prepare_state_frame(build_derived_features(prepare_market_data(fixed_market_frame()).frame))
config = ModelConfig(display_timezone="UTC")
if page == "Advanced State Map":
    _plot(state_map_figure(frame, recent_points=12, timezone="UTC"))
    st.caption("Older = smaller / muted · Previous = open circle · Current = gold star · Latest move = only the last comparable pair")
    st.caption(DISCRETE_STATE_NOTE)
elif page == "Trajectory default":
    render_trajectory(frame, config, 12)
else:
    st.subheader("Advanced: 2D Snapshot Cloud · expanded for screenshot only")
    _plot(snapshot_cloud_figure(frame, recent_n=12, timezone="UTC"))
    st.caption(DISCRETE_STATE_NOTE)
