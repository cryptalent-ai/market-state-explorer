from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
SNAPSHOT_DIR = ROOT / "analysis" / "v0.1.2"

st.set_page_config(
    page_title="Market State Explorer",
    page_icon=None,
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0F0F0F; }
    [data-testid="stMetric"] {
        background: #151515;
        border: 1px solid #2B2B2B;
        padding: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_snapshot() -> tuple[dict, pd.DataFrame]:
    report = json.loads(
        (SNAPSHOT_DIR / "v0.1.2_12month_report.json").read_text(encoding="utf-8")
    )
    candidate = pd.read_csv(SNAPSHOT_DIR / "candidate_30day_vs_12month.csv")
    return report, candidate.sort_values("Horizon")


def candidate_chart(frame: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    x = frame["Horizon"].astype(str)
    for label, suffix, color in (
        ("30-day", "30-Day", "#90A4AE"),
        ("12-month", "12-Month", "#FFD54F"),
    ):
        mean_col = f"Mean ATR Difference vs Baseline {suffix}"
        low_col = f"Difference vs Baseline ATR 95% CI Low {suffix}"
        high_col = f"Difference vs Baseline ATR 95% CI High {suffix}"
        means = frame[mean_col]
        figure.add_trace(
            go.Bar(
                x=x,
                y=means,
                name=label,
                marker={"color": color},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": (frame[high_col] - means).clip(lower=0),
                    "arrayminus": (means - frame[low_col]).clip(lower=0),
                    "visible": True,
                },
                hovertemplate=(
                    f"{label}<br>Horizon: %{{x}} bars"
                    "<br>Difference vs baseline: %{y:.3f} ATR<extra></extra>"
                ),
            )
        )
    figure.add_hline(y=0, line_width=1.5, line_color="#8A8A8A")
    figure.update_layout(
        title="Candidate Stability — Mean ATR Difference vs Baseline",
        paper_bgcolor="#0F0F0F",
        plot_bgcolor="#0F0F0F",
        font={"color": "#E0E0E0"},
        barmode="group",
        margin={"l": 48, "r": 24, "t": 64, "b": 48},
        xaxis_title="Forward horizon (bars)",
        yaxis_title="Conditional mean − baseline mean (ATR)",
    )
    figure.update_xaxes(gridcolor="#2A2A2A")
    figure.update_yaxes(gridcolor="#2A2A2A")
    return figure


st.title("Market State Explorer v0.1.3 — Web Preview")
st.caption(
    "Historical Effort × Result × Positioning research. "
    "State classification is descriptive and is not a trading signal."
)

with st.sidebar:
    section = st.radio(
        "Section",
        ("Research Snapshot", "Methodology", "Explorer Roadmap"),
    )

report, candidate = load_snapshot()
scope = report.get("scope", {})
dataset = report.get("dataset", {})

if section == "Research Snapshot":
    st.header("Research Snapshot")
    st.caption(
        "Read-only 12-month BTCUSDT 5m validation snapshot bundled for the "
        "first public deployment."
    )

    cols = st.columns(6)
    values = (
        ("Market", f"{scope.get('symbol', 'BTCUSDT')} · {scope.get('timeframe', '5m')}"),
        ("Research Period", f"{scope.get('start', '—')} → {scope.get('end', '—')}"),
        ("Bars", f"{int(dataset.get('rows', 0)):,}"),
        ("Kline Coverage", f"{float(dataset.get('kline_coverage', 0.0)):.2%}"),
        ("OI Coverage", f"{float(dataset.get('oi_coverage', 0.0)):.2%}"),
        ("Future OI Matches", f"{int(dataset.get('future_oi_matches', 0)):,}"),
    )
    for col, (label, value) in zip(cols, values):
        col.metric(label, value)

    st.subheader("Pre-specified candidate")
    st.markdown(
        "**High Effort / High Result × Short Covering** — retained as a research "
        "candidate after expanding from a 30-day sample to 12 months."
    )
    st.plotly_chart(candidate_chart(candidate), use_container_width=True)

    table = pd.DataFrame(
        {
            "Horizon": candidate["Horizon"].astype(int),
            "N": candidate["Non-Overlapping N 12-Month"].astype(int),
            "Mean Forward ATR": candidate["Mean Forward ATR 12-Month"],
            "Median Forward ATR": candidate["Median Forward ATR 12-Month"],
            "Difference vs Baseline ATR": candidate[
                "Mean ATR Difference vs Baseline 12-Month"
            ],
            "Difference CI Low": candidate[
                "Difference vs Baseline ATR 95% CI Low 12-Month"
            ],
            "Difference CI High": candidate[
                "Difference vs Baseline ATR 95% CI High 12-Month"
            ],
            "Tail Warning": candidate["Tail-Driven Result Warning 12-Month"],
        }
    )
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.info(
        "The 5-bar and 20-bar 12-month difference intervals are above zero in "
        "this historical sample. The 10-bar interval crosses zero and is "
        "tail-sensitive. This is a robustness observation, not proof of edge."
    )

    st.download_button(
        "Download 30-day vs 12-month comparison",
        candidate.to_csv(index=False).encode("utf-8"),
        file_name="candidate_30day_vs_12month.csv",
        mime="text/csv",
    )

elif section == "Methodology":
    st.header("Methodology")
    st.markdown(
        """
**Effort** asks how unusual current participation is. v0.1.x uses robustly
normalized log Volume and deliberately keeps Open Interest and signed Delta out
of Effort.

**Result** asks how much effective price displacement that participation produced.
It combines ATR-normalized candle-body displacement with directional efficiency.

**Positioning** interprets the joint sign and significance of close-to-close price
change, Delta/Volume, and Open Interest change. Small or ambiguous combinations
remain **Mixed / Low Conviction** rather than being forced into a narrative.

**Historical Validation** then asks what happened 5, 10, and 20 bars later and
compares conditional outcomes with an unconditional baseline.
        """
    )
    st.code(
        "X = Effort (robust z-score)\n"
        "Y = Result (robust z-score)\n"
        "Context = Price × Delta × Open Interest Positioning",
        language="text",
    )
    st.caption(
        "Rolling normalization is past-only: the current observation is excluded "
        "from its own historical reference window."
    )

else:
    st.header("Explorer Roadmap")
    st.markdown(
        """
This first public deployment is intentionally lightweight for free hosting.
The validated local research engine already supports:

- Effort × Result State Map
- Positioning classification from Price × Delta × Open Interest
- State Trajectory
- Historical Forward Validation
- Data Quality diagnostics
- Native Binance BTCUSDT 5m Data Builder
- CSV upload and exports

The next web step is to enable those interactive research pages after this
public snapshot is confirmed stable on the free host.
        """
    )

st.divider()
st.caption(
    "Visualization ≠ Edge · Correlation ≠ Causation · "
    "State Classification ≠ Trade Signal"
)
