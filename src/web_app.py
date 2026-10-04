"""Production Streamlit orchestration for Market State Explorer v1.1."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from .charts import state_map_figure, trajectory_figure
from .config import ModelConfig
from .data_io import DataValidationError, load_market_csv
from .features import build_derived_features
from .live_data import DEFAULT_HISTORY_DAYS, build_recent_market_data
from .relay import RelayMetadata, fetch_public_relay
from .validation import build_validation_summary
from .web_components import candidate_chart, show_current_state, show_quality, validation_chart

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "analysis" / "v0.1.2"
CACHE_ROOT = ROOT / ".web_cache"
WEB_FORWARD_HORIZONS = (5, 10, 15, 20, 30, 60)
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
MAX_WEB_ROWS = 150_000


@st.cache_data(show_spinner=False)
def load_snapshot() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    report = json.loads((SNAPSHOT / "v0.1.2_12month_report.json").read_text("utf-8"))
    candidate = pd.read_csv(SNAPSHOT / "candidate_30day_vs_12month.csv").sort_values("Horizon")
    validation = pd.read_csv(SNAPSHOT / "web_validation_core.csv")
    return report, candidate, validation


@st.cache_data(ttl=300, show_spinner="Refreshing official Binance data...")
def load_binance_dataset(config: ModelConfig):
    market, metadata = build_recent_market_data(cache_root=CACHE_ROOT, history_days=DEFAULT_HISTORY_DAYS)
    derived = build_derived_features(market.frame, config)
    market.quality.warmup_rows = int(derived[["effort_score", "result_score"]].isna().any(axis=1).sum())
    market.quality.usable_state_rows = int(derived[["effort_score", "result_score"]].notna().all(axis=1).sum())
    return derived, market.quality, metadata


@st.cache_data(ttl=60, show_spinner=False)
def load_relay_dataset():
    return fetch_public_relay()


@st.cache_data(show_spinner="Calculating past-only features...")
def calculate_uploaded(csv_bytes: bytes, config: ModelConfig):
    if len(csv_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload exceeds the public-site 60 MB safety limit.")
    market = load_market_csv(BytesIO(csv_bytes))
    if len(market.frame) > MAX_WEB_ROWS:
        raise ValueError(f"Upload has {len(market.frame):,} rows; the public-site limit is {MAX_WEB_ROWS:,}.")
    derived = build_derived_features(market.frame, config)
    market.quality.warmup_rows = int(derived[["effort_score", "result_score"]].isna().any(axis=1).sum())
    market.quality.usable_state_rows = int(derived[["effort_score", "result_score"]].notna().all(axis=1).sum())
    return derived, market.quality


@st.cache_data(show_spinner="Calculating historical validation...")
def calculate_validation(derived: pd.DataFrame, config: ModelConfig, non_overlap: bool) -> pd.DataFrame:
    return build_validation_summary(derived, config, non_overlapping=non_overlap)


def _is_delayed_archive(meta) -> bool:
    return meta is not None and "delayed hosted fallback" in str(getattr(meta, "source", "")).lower()


def _is_relay(meta) -> bool:
    return isinstance(meta, RelayMetadata)


def _freshness_text(meta: RelayMetadata) -> str:
    minutes = meta.age_seconds / 60.0
    if minutes < 1:
        return "under 1 minute ago"
    return f"{minutes:.1f} minutes ago"


def _render_dashboard(active_derived, active_meta, active_error, timezone, scope, dataset, candidate):
    recent_tab, research_tab = st.tabs(("Recent Market State", "12-Month Research Benchmark"))
    with recent_tab:
        if active_derived is None:
            st.warning(active_error or "No active dataset is available.")
        else:
            if _is_relay(active_meta):
                st.success(
                    "Near-real-time relay is active. Official Binance public data were fetched on your local machine "
                    f"and the derived snapshot was published {_freshness_text(active_meta)}."
                )
            elif _is_delayed_archive(active_meta):
                st.warning(
                    "Binance futures REST is unavailable from this hosting region (HTTP 451). "
                    "Showing the latest official daily-archive snapshot instead. This view is delayed "
                    "and must not be treated as the current market state."
                )
            show_current_state(active_derived, timezone)
            if active_meta is not None:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Recent bars", f"{int(active_meta.rows):,}")
                c2.metric("OI coverage", f"{float(active_meta.oi_coverage):.2%}")
                c3.metric("Future OI matches", f"{int(active_meta.future_oi_matches):,}")
                c4.metric("Completed through UTC", str(active_meta.completed_through_utc)[5:16])
                if _is_relay(active_meta):
                    st.caption(
                        "Relay freshness is enforced separately from market-state mathematics. If no successful local update "
                        "arrives for 15 minutes, Auto mode stops treating the relay as current."
                    )
                elif _is_delayed_archive(active_meta):
                    st.caption(
                        "Archive fallback uses official Binance daily files and remains strictly backward-only for OI. "
                        "The completed-through timestamp above is the authoritative freshness marker."
                    )
                else:
                    st.caption("Recent mode excludes the still-open five-minute bar and uses strictly backward OI alignment.")
    with research_tab:
        cols = st.columns(6)
        metrics = (
            ("Market", f"{scope.get('symbol', 'BTCUSDT')} · {scope.get('timeframe', '5m')}"),
            ("Period", f"{scope.get('start', '—')} → {scope.get('end', '—')}"),
            ("Bars", f"{int(dataset.get('rows', 0)):,}"),
            ("Kline Coverage", f"{float(dataset.get('kline_coverage', 0)):.2%}"),
            ("OI Coverage", f"{float(dataset.get('oi_coverage', 0)):.2%}"),
            ("Future OI Matches", f"{int(dataset.get('future_oi_matches', 0)):,}"),
        )
        for col, (label, value) in zip(cols, metrics):
            col.metric(label, value)
        st.subheader("Pre-specified candidate")
        st.markdown("**High Effort / High Result × Short Covering** — tracked across 30 days and 12 months.")
        st.plotly_chart(candidate_chart(candidate), width="stretch")
        st.caption(
            "The bundled audited benchmark was calculated at H=5/10/20 only. H=15/30/60 are never interpolated; "
            "use a sufficiently long active dataset to compute all six horizons."
        )


def _render_validation(active_derived, active_meta, active_source_label, config, snapshot_validation):
    st.header("Historical Forward Validation")
    sources = ["12-month audited snapshot"]
    allow_active = active_derived is not None and not _is_relay(active_meta)
    if allow_active:
        sources.append(f"Active dataset — {active_source_label}")
    source = st.radio("Validation source", sources, horizontal=True)
    if _is_relay(active_meta):
        st.info(
            "The near-real-time relay intentionally publishes only a compact recent derived-state window. "
            "It is used for Current State, State Map and Trajectory—not for forward-validation claims."
        )
    if source.startswith("Active"):
        non_overlap = st.toggle("Non-Overlapping", value=True)
        summary = calculate_validation(active_derived, config, non_overlap)
        st.caption("Recomputed horizons: 5 / 10 / 15 / 20 / 30 / 60 bars (25 / 50 / 75 / 100 / 150 / 300 minutes on 5m data).")
        if active_meta is not None:
            if _is_delayed_archive(active_meta):
                st.info("Archive-fallback validation is based on a short delayed window and is exploratory.")
            else:
                st.info("Recent validation uses only the active window and is exploratory. Use the 12-month snapshot for research conclusions.")
    else:
        summary = snapshot_validation.copy()
        st.caption("BTCUSDT 5m · 2025-09-01 → 2026-08-31 · non-overlapping audited snapshot · available horizons: 5 / 10 / 20 bars.")

    c1, c2, c3 = st.columns(3)
    hs = sorted(summary["Horizon"].astype(int).unique())
    horizons = c1.multiselect("Horizon", hs, default=hs)
    groups_all = sorted(summary["Group Type"].dropna().astype(str).unique())
    groups = c2.multiselect("Validation Group", groups_all, default=groups_all)
    quality_all = sorted(summary["Sample Quality"].dropna().astype(str).unique())
    qualities = c3.multiselect("Sample Quality", quality_all, default=quality_all)
    c4, c5 = st.columns((2, 1))
    text = c4.text_input("Filter group / positioning text", placeholder="e.g. Short Covering, High Effort / High Result").strip().lower()
    ranking = c5.selectbox("Chart ranking", ("Most positive", "Most negative", "Largest absolute"))
    filtered = summary[
        summary["Horizon"].astype(int).isin(horizons)
        & summary["Group Type"].isin(groups)
        & summary["Sample Quality"].isin(qualities)
    ].copy()
    if text:
        haystack = (
            filtered["Group"].fillna("").astype(str)
            + " "
            + filtered["Positioning State"].fillna("").astype(str)
            + " "
            + filtered["Group Type"].fillna("").astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(text, regex=False)]
    st.metric("Displayed rows", f"{len(filtered):,}")
    if filtered.empty:
        st.warning("No rows match the current filters.")
        return
    st.plotly_chart(validation_chart(filtered, ranking), width="stretch")
    columns = [
        "Group Type", "Group", "Positioning State", "Event Direction", "Horizon", "Raw N",
        "Non-Overlapping N", "Mean Forward ATR", "Forward ATR 25th Percentile",
        "Forward ATR 50th Percentile", "Forward ATR 75th Percentile", "Positive Rate",
        "MFE >= 1 ATR", "MAE <= -1 ATR", "Baseline Mean ATR", "Mean ATR Difference vs Baseline",
        "Difference vs Baseline ATR 95% CI Low", "Difference vs Baseline ATR 95% CI High",
        "Mean vs Median Divergence Warning", "Tail-Driven Result Warning", "Sample Quality",
    ]
    available = [column for column in columns if column in filtered.columns]
    st.dataframe(filtered[available], hide_index=True, width="stretch", height=520)
    st.download_button(
        "Download filtered validation CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name="validation_filtered.csv",
        mime="text/csv",
    )


def _load_selected_dataset(data_source: str, upload, config: ModelConfig):
    active_derived = active_quality = active_meta = active_error = None
    active_source_label = data_source

    if data_source in {"Auto (Relay → Archive)", "Near-Real-Time Relay"}:
        try:
            relay_derived, relay_meta = load_relay_dataset()
            if relay_meta.fresh:
                return (
                    relay_derived,
                    None,
                    relay_meta,
                    None,
                    "Near-real-time local relay",
                )
            active_error = (
                f"Relay is stale ({relay_meta.age_seconds / 60:.1f} minutes old). "
                "It will not be presented as current."
            )
        except Exception as error:
            active_error = f"Near-real-time relay unavailable: {error}"
        if data_source == "Near-Real-Time Relay":
            return active_derived, active_quality, active_meta, active_error, active_source_label

    if data_source in {"Auto (Relay → Archive)", "Binance Recent / Archive"}:
        try:
            active_derived, active_quality, active_meta = load_binance_dataset(config)
            if _is_delayed_archive(active_meta):
                active_source_label = "Binance official archive fallback (delayed)"
            else:
                active_source_label = "Binance recent REST/archive"
            return active_derived, active_quality, active_meta, active_error, active_source_label
        except Exception as error:
            active_error = (active_error + " | " if active_error else "") + f"Binance source unavailable: {error}"
            return active_derived, active_quality, active_meta, active_error, active_source_label

    if data_source == "Upload CSV" and upload is not None:
        try:
            active_derived, active_quality = calculate_uploaded(upload.getvalue(), config)
            active_source_label = "Uploaded research CSV"
        except (DataValidationError, ValueError) as error:
            active_error = str(error)
    return active_derived, active_quality, active_meta, active_error, active_source_label


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
    st.title("Market State Explorer v1.1 — Near-Real-Time Relay Edition")
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
        trail_length = st.number_input("Trajectory length", 2, 500, 50)
        if data_source in {"Auto (Relay → Archive)", "Near-Real-Time Relay"}:
            if st.button("Refresh relay", width="stretch"):
                load_relay_dataset.clear()
                st.rerun()
            st.caption("Relay is public derived market data only; no API keys or account data are published.")
        if data_source in {"Auto (Relay → Archive)", "Binance Recent / Archive"}:
            if st.button("Refresh Binance fallback", width="stretch"):
                load_binance_dataset.clear()
                st.rerun()
        st.caption("State-model parameters remain fixed to the audited v0.1.2 defaults. Web validation horizons are 5/10/15/20/30/60 bars.")

    config = ModelConfig(
        display_timezone=timezone,
        display_history=int(display_history),
        trail_length=int(trail_length),
        forward_horizons=WEB_FORWARD_HORIZONS,
    )

    active_derived = active_quality = active_meta = active_error = None
    active_source_label = data_source
    if section != "Methodology":
        active_derived, active_quality, active_meta, active_error, active_source_label = _load_selected_dataset(
            data_source, upload, config
        )

    if _is_relay(active_meta):
        st.sidebar.success(
            f"Relay · {len(active_derived):,} states · {_freshness_text(active_meta)}"
        )
    elif active_derived is not None and _is_delayed_archive(active_meta):
        st.sidebar.warning(
            f"Archive fallback · {len(active_derived):,} rows · OI {active_meta.oi_coverage:.2%}"
        )
    elif active_derived is not None and data_source == "Upload CSV":
        st.sidebar.success(f"Upload · {active_quality.rows_loaded:,} rows · {active_quality.usable_state_rows:,} usable states")
    elif active_derived is not None:
        st.sidebar.success(f"Recent · {len(active_derived):,} rows")
    elif active_error and section != "Methodology":
        st.sidebar.warning(active_error)

    if section == "Dashboard":
        _render_dashboard(active_derived, active_meta, active_error, timezone, scope, dataset, candidate)
    elif section == "State Map":
        st.header("Effort–Result State Map")
        if active_derived is None:
            st.info(active_error or "Choose an available dataset.")
        else:
            if _is_delayed_archive(active_meta):
                st.warning("This state map is based on the delayed official archive fallback.")
            show_current_state(active_derived, timezone)
            st.plotly_chart(
                state_map_figure(active_derived, history=config.display_history, timezone=config.display_timezone),
                width="stretch",
                config={"displaylogo": False, "scrollZoom": True},
            )
    elif section == "Trajectory":
        st.header("State Trajectory")
        if active_derived is None:
            st.info(active_error or "Choose an available dataset.")
        else:
            if _is_delayed_archive(active_meta):
                st.warning("This trajectory is delayed because the hosted app is using official daily archives.")
            usable = active_derived.dropna(subset=["effort_score", "result_score"])
            if len(usable) < 2:
                st.warning("At least two usable states are required.")
            else:
                n = st.slider("N states", 2, min(500, len(usable)), min(config.trail_length, len(usable)))
                st.plotly_chart(
                    trajectory_figure(active_derived, trail_length=n, timezone=config.display_timezone),
                    width="stretch",
                    config={"displaylogo": False, "scrollZoom": True},
                )
    elif section == "Validation":
        _render_validation(active_derived, active_meta, active_source_label, config, snapshot_validation)
    elif section == "Data Quality":
        st.header("Data Quality")
        if active_derived is None:
            st.info(active_error or "Choose an available dataset.")
        elif _is_relay(active_meta):
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
        elif active_quality is not None:
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
    else:
        st.header("Methodology & Guardrails")
        st.markdown(
            """**Effort** measures unusual participation from robustly normalized log Volume.

**Result** measures ATR-normalized price displacement and directional efficiency.

**Positioning** combines price, Delta/Volume, and Open Interest significance; ambiguous combinations remain **Mixed / Low Conviction**.

**Near-real-time relay** runs on the user's own Binance-accessible machine, fetches official public USDⓈ-M data there, computes the existing audited features locally, and publishes only a compact derived-state snapshot to a public GitHub issue comment. The website rejects relay freshness after 15 minutes. No proxy, VPN, geo-bypass, API key, account data, or order execution is used.

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
    st.caption("Visualization ≠ Edge · Correlation ≠ Causation · State Classification ≠ Trade Signal · v1.1")
