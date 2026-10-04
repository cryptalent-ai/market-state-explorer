"""Market State Explorer v0.1.5 — Horizon Expansion Edition."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.charts import state_map_figure, trajectory_figure
from src.config import ModelConfig
from src.data_io import DataValidationError, load_market_csv
from src.features import build_derived_features
from src.formatting import number
from src.validation import build_validation_summary

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "analysis" / "v0.1.2"
WEB_FORWARD_HORIZONS = (5, 10, 15, 20, 30, 60)

st.set_page_config(page_title="Market State Explorer", page_icon=None, layout="wide")
st.markdown(
    """
    <style>
    .stApp { background-color: #0F0F0F; }
    [data-testid="stMetric"] {background:#151515;border:1px solid #2B2B2B;padding:.8rem;}
    .block-container {padding-top:2rem;padding-bottom:3rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_snapshot() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    report = json.loads((SNAPSHOT / "v0.1.2_12month_report.json").read_text("utf-8"))
    candidate = pd.read_csv(SNAPSHOT / "candidate_30day_vs_12month.csv").sort_values("Horizon")
    validation = pd.read_csv(SNAPSHOT / "web_validation_core.csv")
    return report, candidate, validation


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
            x=x,
            y=mean,
            name=label,
            marker_color=color,
            error_y=dict(
                type="data", symmetric=False,
                array=(high - mean).clip(lower=0),
                arrayminus=(mean - low).clip(lower=0), visible=True,
            ),
            hovertemplate=f"{label}<br>Horizon: %{{x}} bars<br>Difference: %{{y:.3f}} ATR<extra></extra>",
        )
    fig.add_hline(y=0, line_width=1.5, line_color="#8A8A8A")
    fig.update_layout(
        title="Candidate Stability — Mean ATR Difference vs Baseline",
        paper_bgcolor="#0F0F0F", plot_bgcolor="#0F0F0F", font_color="#E0E0E0",
        barmode="group", xaxis_title="Forward horizon (bars)",
        yaxis_title="Conditional mean − baseline mean (ATR)",
        margin=dict(l=48, r=24, t=64, b=48),
    )
    fig.update_xaxes(gridcolor="#2A2A2A", type="category", categoryorder="array", categoryarray=x.tolist())
    fig.update_yaxes(gridcolor="#2A2A2A")
    return fig


def validation_chart(frame: pd.DataFrame) -> go.Figure:
    data = frame.dropna(subset=["Mean ATR Difference vs Baseline"]).copy()
    if data.empty:
        return go.Figure()
    data["Label"] = (
        data["Group"].astype(str) + " · " + data["Positioning State"].astype(str)
        + " · H" + data["Horizon"].astype(str)
    )
    data = data.sort_values("Mean ATR Difference vs Baseline", ascending=False).head(15)
    fig = go.Figure(go.Bar(
        x=data["Mean ATR Difference vs Baseline"], y=data["Label"], orientation="h",
        customdata=data[["Non-Overlapping N", "Sample Quality"]],
        hovertemplate="%{y}<br>Difference: %{x:.3f} ATR<br>N: %{customdata[0]}<br>%{customdata[1]}<extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1.5, line_color="#8A8A8A")
    fig.update_layout(
        title="Largest displayed differences vs baseline",
        paper_bgcolor="#0F0F0F", plot_bgcolor="#0F0F0F", font_color="#E0E0E0",
        xaxis_title="Mean Forward ATR − Baseline Mean ATR", yaxis_title=None,
        height=max(440, min(760, 34 * len(data) + 160)), margin=dict(l=24,r=24,t=60,b=40),
    )
    fig.update_xaxes(gridcolor="#2A2A2A")
    fig.update_yaxes(autorange="reversed")
    return fig


def research_label(row: pd.Series) -> str:
    labels = []
    if bool(row.get("lehr_short_pressure", False)): labels.append("LEHR Short Pressure")
    if bool(row.get("lehr_long_pressure", False)): labels.append("LEHR Long Pressure")
    if bool(row.get("helr_event", False)): labels.append("HELR Event")
    return ", ".join(labels) if labels else "None"


def show_quality(report: object) -> None:
    values = report.as_dict()  # type: ignore[attr-defined]
    st.dataframe(pd.DataFrame({"Metric": values.keys(), "Value": [str(v) for v in values.values()]}),
                 hide_index=True, use_container_width=True)


@st.cache_data(show_spinner="Calculating past-only features...")
def calculate_uploaded(csv_bytes: bytes, config: ModelConfig):
    market = load_market_csv(BytesIO(csv_bytes))
    derived = build_derived_features(market.frame, config)
    market.quality.warmup_rows = int(derived[["effort_score","result_score"]].isna().any(axis=1).sum())
    market.quality.usable_state_rows = int(derived[["effort_score","result_score"]].notna().all(axis=1).sum())
    return derived, market.quality


@st.cache_data(show_spinner="Calculating historical validation...")
def calculate_validation(derived: pd.DataFrame, config: ModelConfig, non_overlap: bool) -> pd.DataFrame:
    return build_validation_summary(derived, config, non_overlapping=non_overlap)


report, candidate, snapshot_validation = load_snapshot()
scope, dataset = report.get("scope", {}), report.get("dataset", {})

st.title("Market State Explorer v0.1.5 — Horizon Expansion Edition")
st.caption("Historical Effort × Result × Positioning research. Descriptive research, not a trading signal.")

with st.sidebar:
    st.header("Explorer")
    section = st.radio("Section", ("Dashboard","State Map","Trajectory","Validation","Data Quality","Methodology"))
    st.divider()
    upload = st.file_uploader(
        "Upload research CSV", type=["csv"],
        help="Required: timestamp, open, high, low, close, volume, delta, oi.",
    )
    timezone = st.selectbox("Display Timezone", ("Asia/Taipei","UTC","America/New_York","Europe/London"))
    display_history = st.number_input("State Map history", 50, 5000, 500)
    trail_length = st.number_input("Trajectory length", 2, 500, 50)
    st.caption("State-model parameters remain fixed to the audited v0.1.2 defaults. Validation horizons are expanded to 5/10/15/20/30/60 bars for newly calculated datasets.")

config = ModelConfig(
    display_timezone=timezone,
    display_history=int(display_history),
    trail_length=int(trail_length),
    forward_horizons=WEB_FORWARD_HORIZONS,
)
derived: pd.DataFrame | None = None
quality = None
if upload is not None:
    try:
        derived, quality = calculate_uploaded(upload.getvalue(), config)
        st.sidebar.success(f"{quality.rows_loaded:,} rows · {quality.usable_state_rows:,} usable states")
    except DataValidationError as exc:
        st.sidebar.error("Uploaded CSV failed validation.")
        if section not in {"Dashboard","Validation","Methodology"}:
            st.error(str(exc))
            if exc.report is not None: show_quality(exc.report)
            st.stop()


if section == "Dashboard":
    st.header("12-Month Research Snapshot")
    cols = st.columns(6)
    metrics = (
        ("Market", f"{scope.get('symbol','BTCUSDT')} · {scope.get('timeframe','5m')}"),
        ("Period", f"{scope.get('start','—')} → {scope.get('end','—')}"),
        ("Bars", f"{int(dataset.get('rows',0)):,}"),
        ("Kline Coverage", f"{float(dataset.get('kline_coverage',0)):.2%}"),
        ("OI Coverage", f"{float(dataset.get('oi_coverage',0)):.2%}"),
        ("Future OI Matches", f"{int(dataset.get('future_oi_matches',0)):,}"),
    )
    for col, (label, value) in zip(cols, metrics): col.metric(label, value)
    st.subheader("Pre-specified candidate")
    st.markdown("**High Effort / High Result × Short Covering** — tracked across 30 days and 12 months.")
    st.plotly_chart(candidate_chart(candidate), use_container_width=True)
    st.caption("Bundled audited candidate snapshot was originally calculated at H=5/10/20 only. New H=15/30/60 results are not interpolated; they require recomputation from the underlying bar data.")
    table = pd.DataFrame({
        "Horizon": candidate["Horizon"].astype(int),
        "N": candidate["Non-Overlapping N 12-Month"].astype(int),
        "Mean Forward ATR": candidate["Mean Forward ATR 12-Month"],
        "Median Forward ATR": candidate["Median Forward ATR 12-Month"],
        "Difference vs Baseline ATR": candidate["Mean ATR Difference vs Baseline 12-Month"],
        "Difference CI Low": candidate["Difference vs Baseline ATR 95% CI Low 12-Month"],
        "Difference CI High": candidate["Difference vs Baseline ATR 95% CI High 12-Month"],
        "Tail Warning": candidate["Tail-Driven Result Warning 12-Month"],
    })
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.info("5-bar and 20-bar difference intervals were above zero in this historical sample; 10-bar crossed zero and was tail-sensitive. This is not proof of edge.")

elif section == "State Map":
    st.header("Effort–Result State Map")
    if derived is None:
        st.info("Upload a valid research CSV in the sidebar. The public site intentionally does not bundle the 105,120-bar raw dataset.")
    else:
        usable = derived.dropna(subset=["effort_score","result_score"])
        if usable.empty:
            st.warning("No usable state rows after the warm-up period.")
        else:
            current = usable.iloc[-1]
            cols = st.columns(7)
            values = (
                ("Effort", number(current["effort_score"],2,True)),
                ("Result", number(current["result_score"],2,True)),
                ("Region", str(current["effort_result_region"])),
                ("Positioning", str(current["positioning_state"])),
                ("Strength", number(current["state_strength"],2)),
                ("Velocity", number(current["state_velocity"],2)),
                ("Research", research_label(current)),
            )
            for col, (label, value) in zip(cols, values): col.metric(label, value)
            st.plotly_chart(state_map_figure(derived, history=config.display_history, timezone=config.display_timezone),
                            use_container_width=True, config={"displaylogo":False,"scrollZoom":True})
            if bool(current["near_state_boundary"]):
                st.warning("Current observation is near a zero boundary; treat its region assignment as low confidence.")

elif section == "Trajectory":
    st.header("State Trajectory")
    if derived is None:
        st.info("Upload a valid research CSV in the sidebar to calculate trajectory.")
    else:
        usable = derived.dropna(subset=["effort_score","result_score"])
        if len(usable) < 2:
            st.warning("At least two usable states are required.")
        else:
            n = st.slider("N states", 2, min(500,len(usable)), min(config.trail_length,len(usable)))
            st.plotly_chart(trajectory_figure(derived, trail_length=n, timezone=config.display_timezone),
                            use_container_width=True, config={"displaylogo":False,"scrollZoom":True})
            st.caption("Velocity and acceleration are diagnostics only; v0.1.x derives no trading rule from them.")

elif section == "Validation":
    st.header("Historical Forward Validation")
    sources = ["12-month bundled snapshot"] + (["Uploaded CSV — calculate now"] if derived is not None else [])
    source = st.radio("Validation source", sources, horizontal=True)
    if source.startswith("Uploaded"):
        non_overlap = st.toggle("Non-Overlapping", value=True)
        summary = calculate_validation(derived, config, non_overlap)  # type: ignore[arg-type]
        st.caption("Recomputed horizons: 5 / 10 / 15 / 20 / 30 / 60 bars (25 / 50 / 75 / 100 / 150 / 300 minutes on 5m data).")
    else:
        summary = snapshot_validation.copy()
        st.caption("BTCUSDT 5m · 2025-09-01 → 2026-08-31 · non-overlapping validation snapshot · available horizons: 5 / 10 / 20 bars.")
        st.info("The bundled snapshot predates the horizon expansion. H=15/30/60 are intentionally not fabricated or interpolated. Upload the underlying research CSV to recompute all six horizons.")

    c1,c2,c3 = st.columns(3)
    horizons = c1.multiselect("Horizon", sorted(summary["Horizon"].astype(int).unique()), default=sorted(summary["Horizon"].astype(int).unique()))
    groups_all = sorted(summary["Group Type"].dropna().astype(str).unique())
    groups = c2.multiselect("Validation Group", groups_all, default=groups_all)
    quality_all = sorted(summary["Sample Quality"].dropna().astype(str).unique())
    qualities = c3.multiselect("Sample Quality", quality_all, default=quality_all)
    text = st.text_input("Filter group / positioning text", placeholder="e.g. Short Covering, High Effort / High Result").strip().lower()
    filtered = summary[summary["Horizon"].astype(int).isin(horizons) & summary["Group Type"].isin(groups) & summary["Sample Quality"].isin(qualities)].copy()
    if text:
        haystack = (filtered["Group"].fillna("").astype(str)+" "+filtered["Positioning State"].fillna("").astype(str)+" "+filtered["Group Type"].fillna("").astype(str)).str.lower()
        filtered = filtered[haystack.str.contains(text, regex=False)]
    st.metric("Displayed rows", f"{len(filtered):,}")
    if filtered.empty:
        st.warning("No rows match the current filters.")
    else:
        st.plotly_chart(validation_chart(filtered), use_container_width=True)
        columns = [
            "Group Type","Group","Positioning State","Event Direction","Horizon","Raw N","Non-Overlapping N",
            "Mean Forward ATR","Forward ATR 25th Percentile","Forward ATR 50th Percentile","Forward ATR 75th Percentile",
            "Positive Rate","MFE >= 1 ATR","MAE <= -1 ATR","Baseline Mean ATR","Mean ATR Difference vs Baseline",
            "Difference vs Baseline ATR 95% CI Low","Difference vs Baseline ATR 95% CI High",
            "Mean vs Median Divergence Warning","Tail-Driven Result Warning","Sample Quality",
        ]
        available_columns = [column for column in columns if column in filtered.columns]
        st.dataframe(filtered[available_columns], hide_index=True, use_container_width=True, height=520)
        st.download_button("Download filtered validation CSV", filtered.to_csv(index=False).encode("utf-8"),
                           file_name="validation_filtered.csv", mime="text/csv")

elif section == "Data Quality":
    st.header("Data Quality")
    if derived is None or quality is None:
        st.info("Upload a research CSV for row-level checks. The bundled 12-month build had 100% Kline coverage, 99.998% OI coverage, zero invalid Delta rows, and zero future OI matches.")
    else:
        show_quality(quality)
        flagged = derived[derived["data_quality_flag"].ne("")][["timestamp","data_quality_flag"]]
        if flagged.empty: st.success("No row-level Explorer data-quality flags were detected.")
        else: st.dataframe(flagged, hide_index=True, use_container_width=True)

else:
    st.header("Methodology")
    st.markdown("""
**Effort** asks how unusual current participation is. It uses robustly normalized log Volume and keeps OI and signed Delta out of Effort.

**Result** measures effective price displacement using ATR-normalized candle-body displacement and directional efficiency.

**Positioning** interprets the joint sign/significance of close-to-close price change, Delta/Volume, and OI change. Ambiguous combinations remain **Mixed / Low Conviction**.

**Validation** compares 5/10/15/20/30/60-bar conditional outcomes with an unconditional baseline for newly calculated datasets, while the bundled legacy snapshot remains 5/10/20. It surfaces sample size, percentiles, confidence intervals, and tail warnings.
    """)
    st.code("X = Effort (robust z-score)\nY = Result (robust z-score)\nContext = Price × Delta × Open Interest Positioning", language="text")
    st.caption("Rolling normalization is past-only: the current observation is excluded from its own historical reference window.")

if derived is not None:
    st.sidebar.download_button("Download derived_features.csv", derived.to_csv(index=False).encode("utf-8"),
                               file_name="derived_features.csv", mime="text/csv")

st.divider()
st.caption("Visualization ≠ Edge · Correlation ≠ Causation · State Classification ≠ Trade Signal")
