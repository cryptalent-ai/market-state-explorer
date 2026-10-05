"""Market State Explorer v1.2 — Visual Clarity Edition."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .charts import state_map_figure, trajectory_figure
from .config import ModelConfig
from .visual_insights import state_map_insight, trajectory_insight
from .web_app import (
    WEB_FORWARD_HORIZONS,
    _freshness_text,
    _is_delayed_archive,
    _is_relay,
    _load_selected_dataset,
    _render_dashboard,
    _render_validation,
    load_binance_dataset,
    load_relay_dataset,
    load_snapshot,
)
from .web_components import show_current_state, show_quality


def _sidebar_status(active_derived, active_quality, active_meta, active_error, data_source: str, section: str) -> None:
    if _is_relay(active_meta):
        st.sidebar.success(f"Relay · {len(active_derived):,} states · {_freshness_text(active_meta)}")
    elif active_derived is not None and _is_delayed_archive(active_meta):
        st.sidebar.warning(f"Archive fallback · {len(active_derived):,} rows · OI {active_meta.oi_coverage:.2%}")
    elif active_derived is not None and data_source == "Upload CSV":
        st.sidebar.success(
            f"Upload · {active_quality.rows_loaded:,} rows · {active_quality.usable_state_rows:,} usable states"
        )
    elif active_derived is not None:
        st.sidebar.success(f"Recent · {len(active_derived):,} rows")
    elif active_error and section != "Methodology":
        st.sidebar.warning(active_error)


def _state_map_page(active_derived, active_meta, active_error, config: ModelConfig) -> None:
    st.header("Effort–Result State Map")
    st.caption("Historical context is compressed into density by default; recent states and the current state stay readable.")
    if active_derived is None:
        st.info(active_error or "Choose an available dataset.")
        return
    if _is_delayed_archive(active_meta):
        st.warning("This state map is based on the delayed official archive fallback.")
    show_current_state(active_derived, config.display_timezone)
    st.info(state_map_insight(active_derived, lookback=12))

    c1, c2, c3 = st.columns((1.2, 1, 1))
    mode = c1.selectbox("Map view", ("Density + recent", "Recent only", "Full scatter"), index=0)
    recent_points = c2.select_slider("Recent states", options=(5, 8, 12, 20, 30, 50), value=20)
    color_by = c3.selectbox("Full-scatter color", ("Direction", "Positioning"), index=0)
    st.plotly_chart(
        state_map_figure(
            active_derived,
            history=config.display_history,
            timezone=config.display_timezone,
            mode=mode,
            recent_points=int(recent_points),
            color_by=color_by,
        ),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
    )
    if mode != "Full scatter":
        st.caption("Use Full scatter only for drill-down. Density + recent is the recommended default for decision-oriented reading.")


def _trajectory_page(active_derived, active_meta, active_error, config: ModelConfig) -> None:
    st.header("State Trajectory")
    st.caption("The default window is intentionally short so direction is visible instead of turning into a spaghetti path.")
    if active_derived is None:
        st.info(active_error or "Choose an available dataset.")
        return
    if _is_delayed_archive(active_meta):
        st.warning("This trajectory is delayed because the hosted app is using official daily archives.")
    usable = active_derived.dropna(subset=["effort_score", "result_score"])
    if len(usable) < 2:
        st.warning("At least two usable states are required.")
        return

    c1, c2 = st.columns((1.3, 1))
    view = c1.selectbox(
        "View",
        ("2D trajectory", "Effort over time", "Result over time", "Strength / Velocity"),
        index=0,
    )
    allowed = [value for value in (5, 8, 12, 20, 30) if value <= len(usable)]
    if not allowed:
        allowed = [len(usable)]
    default_n = 12 if 12 in allowed else allowed[-1]
    n = c2.select_slider("Recent valid states", options=allowed, value=default_n)
    st.info(trajectory_insight(active_derived, lookback=int(n)))
    st.plotly_chart(
        trajectory_figure(
            active_derived,
            trail_length=int(n),
            timezone=config.display_timezone,
            view=view,
        ),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
    )
    st.caption("2D view highlights Start, Previous, Current and the latest move. Time-series views are often clearer for trend inspection.")


def _data_quality_page(active_derived, active_quality, active_meta, active_error) -> None:
    st.header("Data Quality")
    if active_derived is None:
        st.info(active_error or "Choose an available dataset.")
        return
    if _is_relay(active_meta):
        st.subheader("Near-real-time relay audit")
        meta = active_meta.as_dict()
        st.dataframe(
            pd.DataFrame({"Metric": meta.keys(), "Value": [str(value) for value in meta.values()]}),
            hide_index=True,
            width="stretch",
        )
        flagged = active_derived[
            active_derived["data_quality_flag"].fillna("").astype(str).ne("")
        ][["timestamp", "data_quality_flag"]]
        if flagged.empty:
            st.success("No published row-level Explorer data-quality flags were present in the relay window.")
        else:
            st.dataframe(flagged, hide_index=True, width="stretch")
        return

    if active_quality is None:
        st.info("No row-level quality report is available for this source.")
        return
    show_quality(active_quality)
    if active_meta is not None:
        st.subheader("Official-source audit")
        meta = active_meta.as_dict()
        keys = (
            "source", "requested_start", "requested_end", "as_of_utc", "completed_through_utc",
            "rows", "oi_coverage", "missing_oi_rows", "stale_oi_rows", "future_oi_matches",
            "cache_hits", "downloads", "missing_kline_dates", "missing_oi_dates",
        )
        st.dataframe(
            pd.DataFrame({"Metric": keys, "Value": [str(meta[key]) for key in keys]}),
            hide_index=True,
            width="stretch",
        )
    flagged = active_derived[
        active_derived["data_quality_flag"].fillna("").astype(str).ne("")
    ][["timestamp", "data_quality_flag"]]
    if flagged.empty:
        st.success("No row-level Explorer data-quality flags were detected.")
    else:
        st.dataframe(flagged, hide_index=True, width="stretch")


def run() -> None:
    st.set_page_config(page_title="Market State Explorer", page_icon=None, layout="wide")
    st.markdown(
        """<style>
        .stApp{background-color:#0F0F0F}
        [data-testid="stMetric"]{background:#151515;border:1px solid #2B2B2B;padding:.8rem}
        [data-testid="stMetricValue"]{font-size:1.55rem}
        .block-container{padding-top:1.6rem;padding-bottom:3rem}
        </style>""",
        unsafe_allow_html=True,
    )
    report, candidate, snapshot_validation = load_snapshot()
    scope, dataset = report.get("scope", {}), report.get("dataset", {})
    st.title("Market State Explorer v1.2 — Visual Clarity Edition")
    st.caption("Effort × Result × Positioning research with official Binance data. Descriptive research, not a trading signal.")

    with st.sidebar:
        st.header("Explorer")
        section = st.radio("Section", ("Dashboard", "State Map", "Trajectory", "Validation", "Data Quality", "Methodology"))
        st.divider()
        data_source = st.radio(
            "Active dataset",
            ("Auto (Relay → Archive)", "Near-Real-Time Relay", "Binance Recent / Archive", "Upload CSV"),
        )
        upload = (
            st.file_uploader(
                "Upload research CSV",
                type=["csv"],
                help="Required: timestamp, open, high, low, close, volume, delta, oi.",
            )
            if data_source == "Upload CSV"
            else None
        )
        timezone = st.selectbox("Display Timezone", ("Asia/Taipei", "UTC", "America/New_York", "Europe/London"))
        display_history = st.number_input("State Map history", 50, 5000, 500)
        if data_source in {"Auto (Relay → Archive)", "Near-Real-Time Relay"}:
            if st.button("Refresh relay", width="stretch"):
                load_relay_dataset.clear()
                st.rerun()
            st.caption("Relay is public derived market data only; no API keys or account data are published.")
        if data_source in {"Auto (Relay → Archive)", "Binance Recent / Archive"}:
            if st.button("Refresh Binance fallback", width="stretch"):
                load_binance_dataset.clear()
                st.rerun()
        st.caption("Model mathematics stay frozen to the audited v0.1.2 defaults. v1.2 changes visual presentation only.")

    config = ModelConfig(
        display_timezone=timezone,
        display_history=int(display_history),
        trail_length=12,
        forward_horizons=WEB_FORWARD_HORIZONS,
    )

    active_derived = active_quality = active_meta = active_error = None
    active_source_label = data_source
    if section != "Methodology":
        active_derived, active_quality, active_meta, active_error, active_source_label = _load_selected_dataset(
            data_source, upload, config
        )
    _sidebar_status(active_derived, active_quality, active_meta, active_error, data_source, section)

    if section == "Dashboard":
        _render_dashboard(active_derived, active_meta, active_error, timezone, scope, dataset, candidate)
    elif section == "State Map":
        _state_map_page(active_derived, active_meta, active_error, config)
    elif section == "Trajectory":
        _trajectory_page(active_derived, active_meta, active_error, config)
    elif section == "Validation":
        _render_validation(active_derived, active_meta, active_source_label, config, snapshot_validation)
    elif section == "Data Quality":
        _data_quality_page(active_derived, active_quality, active_meta, active_error)
    else:
        st.header("Methodology & Guardrails")
        st.markdown(
            """**Effort** measures unusual participation from robustly normalized log Volume.

**Result** measures ATR-normalized price displacement and directional efficiency.

**Positioning** combines price, Delta/Volume, and Open Interest significance; ambiguous combinations remain **Mixed / Low Conviction**.

**Visual clarity layer (v1.2)** compresses historical state-map points into density by default, overlays only a short recent path, and limits the default 2D trajectory to 12 valid states. Time-series alternatives expose Effort, Result, Strength and Velocity directly. These changes do not modify the underlying state mathematics.

**Near-real-time relay** runs on the user's own Binance-accessible machine and publishes only compact derived public-market state data. The website rejects relay freshness after 15 minutes.

**Hosted fallback** uses official Binance daily archives when Streamlit Cloud receives HTTP 451. It is delayed and is never labelled current.

**Validation** uses 5/10/15/20/30/60-bar horizons for sufficiently long active datasets. The bundled 12-month audited snapshot remains 5/10/20 because those were the horizons actually computed when frozen."""
        )
        st.caption("Rolling normalization is past-only: the current observation is excluded from its own historical reference window.")

    if active_derived is not None:
        st.sidebar.download_button(
            "Download derived_features.csv",
            active_derived.to_csv(index=False).encode("utf-8"),
            file_name="derived_features.csv",
            mime="text/csv",
        )
    st.divider()
    st.caption("Visualization ≠ Edge · Correlation ≠ Causation · State Classification ≠ Trade Signal · v1.2")
