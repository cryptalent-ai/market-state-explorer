"""v1.3 presentation; data acquisition and audited models remain frozen."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from . import charts_v12
from .charts_v13 import REGION_COLORS, small_multiples_figure, state_matrix_figure, timeline_ribbon_figure
from .config import ModelConfig
from .formatting import number, timestamp
from .state_views import (
    boundary_label, build_timeline_frame, compute_recent_state_summary,
    compute_region_occupancy, compute_state_rarity, extract_region_transitions, flag,
    match_current_validation_rows, prepare_state_frame, research_label, switching_label,
)
from .web_app import (
    WEB_FORWARD_HORIZONS, _freshness_text, _is_delayed_archive, _is_relay,
    _load_selected_dataset, _render_validation, load_binance_dataset,
    load_relay_dataset, load_snapshot,
)
from .web_app_v12 import _data_quality_page, _sidebar_status
from .web_components import candidate_chart

STYLE = """<style>
.stApp{background-color:#0F0F0F}.block-container{padding-top:1.2rem;padding-bottom:3rem}
.v13-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:8px 0}
.v13-grid.compact{grid-template-columns:repeat(var(--columns),minmax(0,1fr))}
.v13-grid.compact .v13-card{padding:10px}.v13-grid.compact .v13-value{font-size:1rem}
[data-testid="stHeadingWithActionElements"] h1{font-size:2.1rem}
.v13-card{background:#171A1D;border:1px solid #39424B;border-radius:8px;padding:12px;min-width:0}
.v13-card.current{border-color:#FFD54F}.v13-title{font-size:.78rem;color:#ABB7C4;margin-bottom:5px}
.v13-value{font-size:1.08rem;color:#F2F2F2;line-height:1.35;white-space:normal;overflow-wrap:anywhere}
.v13-note{font-size:.8rem;color:#BAC4CF;margin-top:4px;line-height:1.4}
.v13-table{width:100%;border-collapse:collapse;font-size:.83rem;table-layout:auto}
.v13-table th,.v13-table td{padding:8px;border-bottom:1px solid #39424B;text-align:left;white-space:normal;overflow-wrap:anywhere}
.v13-table th{color:#BAC4CF}.v13-table tr:first-child td{background:#1D2227}
.v13-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.75rem;color:#CFD8E3;margin:5px 0 10px}
.v13-dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.v13-observation{border-left:3px solid #FFD54F;background:#1D1C17;padding:8px 12px;margin:12px 0 8px}
.v13-overview{margin:10px 0 16px}.v13-overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 24px;margin:10px 0}
@media(max-width:650px){.v13-overview-grid{grid-template-columns:1fr}}
@media(max-width:650px){.v13-table{font-size:.72rem}.v13-table th,.v13-table td{padding:5px}.v13-grid{grid-template-columns:1fr}.v13-grid.compact{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>"""


def _cards(items, current=False, compact=False):
    cards = []
    for label, value, note in items:
        cards.append(f'<div class="v13-card{" current" if current else ""}"><div class="v13-title">{escape(str(label))}</div><div class="v13-value">{escape(str(value))}</div><div class="v13-note">{escape(str(note))}</div></div>')
    st.markdown(f'<div class="v13-grid{" compact" if compact else ""}" style="--columns:{len(items)}">' + ''.join(cards) + '</div>', unsafe_allow_html=True)


def _table(frame):
    st.markdown(frame.to_html(index=False, classes="v13-table", border=0, escape=True, na_rep="—"), unsafe_allow_html=True)


def _plot(figure):
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})


def _source_status(meta, source_label, error):
    if _is_relay(meta):
        st.success(f"RELAY PUBLICATION FRESHNESS · Near-real-time Relay active · published {_freshness_text(meta)}")
        st.caption(f"Relay published at UTC {meta.updated_at_utc} · dataset completed through UTC {meta.completed_through_utc}. Publication age is not the market-bar timestamp.")
    elif _is_delayed_archive(meta):
        st.warning(f"Delayed official Archive fallback — NOT the current market state · completed through UTC {meta.completed_through_utc}")
        if error:
            st.caption(error)
    elif meta is not None:
        st.info(f"{source_label} · completed through UTC {meta.completed_through_utc}")
    else:
        st.info(f"{source_label} · latest observation in the selected dataset; no live freshness claim")


def render_current_state(frame, timezone):
    current = frame.iloc[-1]
    st.markdown('<div class="v13-observation"><div class="v13-title">LATEST VALID STATE · MARKET-BAR TIMESTAMP</div>'
                f'<div class="v13-value">{escape(timestamp(current["timestamp"], timezone))} · {escape(timezone)}</div>'
                '<div class="v13-note">Observation time in the selected dataset; source / publication freshness is shown separately above.</div></div>', unsafe_allow_html=True)
    _cards([
        ("Current / latest Effort–Result Region", current["effort_result_region"], boundary_label(current)),
        ("Current / latest Positioning State", current["positioning_state"], "Existing audited classification"),
    ], current=True)
    _cards([
        ("Effort", number(current["effort_score"], 2, signed=True), ""),
        ("Result", number(current["result_score"], 2, signed=True), ""),
        ("Strength", number(current['state_strength'], 2), ""),
        ("Velocity", number(current['state_velocity'], 2), ""),
        ("Research Event", research_label(current), ""),
    ], compact=True)


def render_recent_summary(frame, recent_n):
    summary = compute_recent_state_summary(frame, recent_n)
    if not summary["n"]:
        st.info("No valid states are available.")
        return
    n = summary["n"]
    st.subheader(f"Recent {n}-state summary")
    st.write(f"{summary['dominant_region']} dominated {summary['dominant_region_count']}/{n} states. "
             f"Positioning: {summary['dominant_positioning']} occupied {summary['dominant_positioning_count']}/{n}. "
             f"Region changed {summary['region_transitions']} times; Positioning changed {summary['positioning_transitions']} times "
             f"across {summary['comparable_steps']} adjacent steps. {summary['boundary']}.")
    st.caption(f"Net change: Effort {number(summary['net_effort'], 2, signed=True)}, Result {number(summary['net_result'], 2, signed=True)}. "
               f"Latest one-step change: Effort {number(summary['latest_effort'], 2, signed=True)}, Result {number(summary['latest_result'], 2, signed=True)}. "
               f"Window discontinuities: {summary['gaps']}; transitions and changes never bridge missing bars or segment boundaries.")


def render_ribbon(frame, recent_n, timezone, *, recent_categories_only=False):
    st.subheader("Recent state timeline · oldest → latest")
    _plot(timeline_ribbon_figure(frame, recent_n, timezone))
    recent = build_timeline_frame(frame, recent_n)
    for title, mapping in (("Region", REGION_COLORS), ("Positioning", charts_v12.POSITIONING_COLORS)):
        present = set(recent["effort_result_region" if title == "Region" else "positioning_state"])
        colors = {**mapping, **{label: "#303438" for label in sorted(present - mapping.keys())}}
        labels = ''.join(f'<span><i class="v13-dot" style="background:{color}"></i>{escape(label)}</span>' for label, color in colors.items() if label in present or (title == "Region" and not recent_categories_only))
        st.markdown(f'<div class="v13-note">{title}</div><div class="v13-legend">{labels}</div>', unsafe_allow_html=True)
    st.caption("Research: gray = none, muted gold = an existing event (full name in hover). Boundary: pale neutral = near zero; gray = not near zero. Unknown = charcoal. Gold outline = latest observation, not a trade instruction.")


def render_recent_table(frame, timezone):
    recent = build_timeline_frame(frame, 5).iloc[::-1]
    rows = [{"Timestamp": timestamp(r["timestamp"], timezone), "Effort": number(r["effort_score"], 2),
             "Result": number(r["result_score"], 2), "Region": r["effort_result_region"],
             "Positioning": r["positioning_state"], "Strength": number(r["state_strength"], 2),
             "Velocity": number(r["state_velocity"], 2), "Research Event": research_label(r)} for _, r in recent.iterrows()]
    st.subheader("Recent 5 valid states · newest first")
    _table(pd.DataFrame(rows))


def render_validation_snapshot(current, validation):
    st.subheader("Current-State Validation Snapshot")
    st.caption("BTCUSDT 5m · 2025-09-01 → 2026-08-31 audited historical benchmark · non-overlapping H=5/10/20 only. Not calculated from the Relay window. No interpolation, causation or trading-edge claim.")
    matched = match_current_validation_rows(current, validation)
    if matched.empty or not matched["Adequate sample"].any():
        st.warning("No sufficiently matched historical validation sample is available for the current state.")
    if matched.empty:
        return
    st.caption("Priority per horizon: Region × Positioning → Positioning → Region, preferring adequate samples. Marginal fallback is broader, not joint-state evidence. Exploratory is not a usable research sample; insufficient rows are displayed only as limitations. Median uses the published 50th percentile when the compact snapshot omits a separate median field.")
    rows = []
    for _, r in matched.iterrows():
        tail = flag(r.get("Tail-Driven Result Warning"))
        rows.append({"Horizon": f"{int(r['Horizon'])} bars", "Matched scope": r["Matched scope"],
                     "Non-Overlapping N": number(r.get("Non-Overlapping N"), 0),
                     "Mean Forward ATR": number(r.get("Mean Forward ATR"), 3),
                     "Median Forward ATR": number(r.get("Median Forward ATR", r.get("Forward ATR 50th Percentile")), 3),
                     "Difference vs Baseline ATR": number(r.get("Mean ATR Difference vs Baseline"), 3),
                     "Difference vs Baseline 95% CI (ATR)": f"[{number(r.get('Difference vs Baseline ATR 95% CI Low'), 3)}, {number(r.get('Difference vs Baseline ATR 95% CI High'), 3)}]",
                     "Positive Rate": f"{number(100 * r.get('Positive Rate', float('nan')), 1)}%",
                     "Sample Quality": r["Sample Quality"],
                     "Tail Warning": "Tail-driven warning" if tail is True else "No warning" if tail is False else "Unavailable"})
    _table(pd.DataFrame(rows))


def _decision_strip(frame, history, recent_n, validation):
    summary = compute_recent_state_summary(frame, recent_n)
    rarity = compute_state_rarity(frame, history)
    matched = match_current_validation_rows(frame.iloc[-1], validation)
    quality = "No adequate historical sample" if matched.empty or not matched["Adequate sample"].any() else " · ".join(sorted(set(matched["Sample Quality"])))
    sample_note = "No matched row" if matched.empty else "; ".join(f"H{int(r['Horizon'])}: N={number(r.get('Non-Overlapping N'),0)} ({r['Matched scope']})" for _, r in matched.iterrows())
    _cards([
        (f"Dominant Region · recent {summary['n']}", summary["dominant_region"], f"{summary['dominant_region_count']} / {summary['n']} states"),
        ("Persistence / switching", switching_label(summary['region_transitions'], summary['comparable_steps']), f"Region: {summary['region_transitions']} changes / {summary['comparable_steps']} comparable steps · Positioning: {summary['positioning_transitions']} changes · {summary['gaps']} discontinuities. UI description only."),
        ("Current Region · visible history", f"{number(rarity['Current region frequency %'], 1)}% · {rarity['Frequency description']}", f"N={rarity['n']} valid states; descriptive frequency, not predictive rarity"),
        ("Historical validation sample", quality, sample_note),
    ], compact=True)


def render_dashboard(frame, meta, error, source_label, config, history, recent_n, validation):
    _source_status(meta, source_label, error)
    render_current_state(frame, config.display_timezone)
    _decision_strip(frame, history, recent_n, validation)
    st.subheader("Effort–Result State Matrix")
    _plot(state_matrix_figure(frame, history, recent_n))
    st.caption("Occupancy uses active already-derived valid states only. Both windows include the latest observation. Relay is limited to its published window, not a full-year frequency estimate.")
    render_ribbon(frame, recent_n, config.display_timezone)
    render_recent_summary(frame, recent_n)
    render_recent_table(frame, config.display_timezone)
    render_validation_snapshot(frame.iloc[-1], validation)


def render_state_map(frame, config, history, recent_n):
    render_current_state(frame, config.display_timezone)
    st.subheader("Categorical State Matrix")
    _plot(state_matrix_figure(frame, history, recent_n))
    st.subheader("Historical vs recent occupancy")
    occupancy = compute_region_occupancy(frame, history, recent_n)
    comparison = occupancy[["Region", "Historical %", "Recent %", "Recent − historical pp"]].copy()
    for c in comparison.columns[1:]:
        comparison[c] = comparison[c].map(lambda v: number(v, 1))
    _table(comparison)
    rarity = compute_state_rarity(frame, history)
    st.subheader("Current-state percentile / frequency")
    _cards([(name, f"{number(rarity[name + ' percentile'], 1)}th percentile", f"N={rarity[name+' N']}") for name in ("Effort", "Result", "Strength")] + [("Current Region frequency", f"{number(rarity['Current region frequency %'], 1)}%", rarity["Frequency description"])])
    st.caption(f"Percentile = percentage of finite observations ≤ latest value, including latest, in the selected visible history ({rarity['n']} valid states). Frequency ranks compare the four existing regions. No rarity thresholds or predictive labels are introduced.")
    with st.expander("Advanced: 2D state-space views", expanded=False):
        mode = st.selectbox("Map view", ("Density + recent", "Recent only", "Full scatter"))
        color = st.selectbox("Full-scatter color", ("Direction", "Positioning"))
        _plot(charts_v12.state_map_figure(frame, history=len(frame) if history is None else history,
                                        timezone=config.display_timezone, mode=mode, recent_points=recent_n, color_by=color))


def render_trajectory_summary(frame, recent_n):
    summary = compute_recent_state_summary(frame, recent_n)
    if not summary["n"]:
        st.info("No valid states are available for the recent-state overview.")
        return
    steps = summary["comparable_steps"]
    region_changes = summary["region_transitions"]
    positioning_changes = summary["positioning_transitions"]
    current = build_timeline_frame(frame, recent_n).iloc[-1]
    items = [
        ("Dominant recent Region", summary["dominant_region"], f"{summary['dominant_region_count']} / {summary['n']} states"),
        ("Dominant recent Positioning", summary["dominant_positioning"], f"{summary['dominant_positioning_count']} / {summary['n']} states"),
        ("Switching intensity · Region", switching_label(region_changes, steps), f"Region: {region_changes} / {steps} comparable steps; Positioning: {switching_label(positioning_changes, steps)} ({positioning_changes} / {steps})"),
        ("Current Region", current["effort_result_region"], "Latest valid observation"),
        ("Zero-boundary status", summary["boundary"], "Existing audited boundary flag"),
    ]
    fields = ''.join(f'<div><div class="v13-title">{escape(label)}</div><div class="v13-value">{escape(value)}</div><div class="v13-note">{escape(note)}</div></div>' for label, value, note in items)
    st.markdown(f'<div class="v13-card current v13-overview"><div class="v13-title">RECENT {summary["n"]}-STATE OVERVIEW</div><div class="v13-overview-grid">{fields}</div>'
                f'<div class="v13-note">{summary["gaps"]} discontinuities excluded. Switching wording only: ≤ 1/3 = Mostly stable; ≥ 2/3 = Frequent switching; otherwise Moderate switching. No comparable steps = Unavailable. Not a model signal.</div></div>', unsafe_allow_html=True)


def render_trajectory(frame, config, recent_n):
    render_trajectory_summary(frame, recent_n)
    render_ribbon(frame, recent_n, config.display_timezone, recent_categories_only=True)
    render_recent_summary(frame, recent_n)
    st.subheader("Chronological state measurements")
    _plot(small_multiples_figure(frame, recent_n, config.display_timezone))
    st.subheader("Region transitions · chronological")
    transitions = extract_region_transitions(frame, recent_n)
    if transitions.empty:
        st.info("No Region changes across adjacent observations in this window.")
    else:
        transitions["timestamp"] = transitions["timestamp"].map(lambda v: timestamp(v, config.display_timezone))
        for c in ("effort_score", "result_score"):
            transitions[c] = transitions[c].map(lambda v: number(v, 2))
        _table(transitions.rename(columns={"timestamp": "Timestamp", "From": "From Region", "To": "To Region", "effort_score": "Effort", "result_score": "Result"}))
    with st.expander("Advanced: 2D phase trajectory", expanded=False):
        _plot(charts_v12.trajectory_figure(frame, trail_length=recent_n, timezone=config.display_timezone, view="2D trajectory"))


def run():
    st.set_page_config(page_title="Market State Explorer v1.3", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    st.title("Market State Explorer v1.3")
    st.caption("Decision-Oriented Visual Edition · descriptive research, not trading recommendations")
    report, candidate, validation = load_snapshot()
    with st.sidebar:
        st.header("Explorer")
        section = st.radio("Section", ("Dashboard", "State Map", "Trajectory", "Validation", "Data Quality", "Methodology"))
        source = st.radio("Active dataset", ("Auto (Relay → Archive)", "Near-Real-Time Relay", "Binance Recent / Archive", "Upload CSV"))
        upload = st.file_uploader("Upload research CSV", type=["csv"], help="Required: timestamp, open, high, low, close, volume, delta, oi.") if source == "Upload CSV" else None
        timezone = st.selectbox("Display Timezone", ("Asia/Taipei", "UTC", "America/New_York", "Europe/London"))
        history_choice = st.selectbox("Historical window", (250, 500, 1000, "All available"), index=1)
        history = None if history_choice == "All available" else int(history_choice)
        recent_n = st.select_slider("Recent valid states", options=(5, 8, 12, 20, 30), value=12)
        if source in {"Auto (Relay → Archive)", "Near-Real-Time Relay"} and st.button("Refresh relay", width="stretch"):
            load_relay_dataset.clear()
            st.rerun()
        if source in {"Auto (Relay → Archive)", "Binance Recent / Archive"} and st.button("Refresh Binance fallback", width="stretch"):
            load_binance_dataset.clear()
            st.rerun()
        st.caption("Frozen audited model. Windows affect presentation only. Relay freshness remains 15 minutes; archives remain delayed.")
    config = ModelConfig(display_timezone=timezone, display_history=history or 500, trail_length=12, forward_horizons=WEB_FORWARD_HORIZONS)
    active = quality = meta = error = None
    label = source
    if section != "Methodology":
        active, quality, meta, error, label = _load_selected_dataset(source, upload, config)
    _sidebar_status(active, quality, meta, error, source, section)
    if section == "Methodology":
        st.header("Methodology & Guardrails")
        st.markdown("Effort, Result, Positioning, thresholds, boundary logic and Research Events are unchanged. Rolling reference windows exclude the current observation; OI alignment is backward-only. Forward outcomes and non-overlapping validation are unchanged.")
        st.markdown("The v1.3 presentation reads already-derived states: categorical occupancy, chronological ribbons, observed transitions, finite-sample percentiles and published validation-row matching. Missing optional fields are unavailable, never reconstructed. Discontinuities are not counted as transitions.")
        st.markdown("Relay data is current only while fresh under the existing 15-minute rule. HTTP 451 falls back to official delayed archives. CSV calculations use the same audited pipeline. Dashboard validation uses the bundled 2025-09-01 → 2026-08-31 BTCUSDT 5m benchmark; it is historical context, not a prediction for the Relay state. Validation retains existing active-dataset sampling controls and 5/10/15/20/30/60 horizons.")
    elif section == "Validation":
        _render_validation(active, meta, label, config, validation)
    elif section == "Data Quality":
        _data_quality_page(active, quality, meta, error)
    elif active is None:
        st.warning(error or "Choose an available dataset.")
    else:
        frame = prepare_state_frame(active)
        if frame.empty:
            st.warning("No valid derived states are available; check Data Quality and model warm-up coverage.")
        elif section == "Dashboard":
            render_dashboard(frame, meta, error, label, config, history, int(recent_n), validation)
            with st.expander("Audited pre-specified candidate benchmark"):
                st.caption("High Effort / High Result × Short Covering · frozen 30-day vs 12-month results · H5/10/20")
                _plot(candidate_chart(candidate))
                st.json(report.get("scope", {}))
        else:
            _source_status(meta, label, error)
            if section == "State Map":
                render_state_map(frame, config, history, int(recent_n))
            else:
                render_trajectory(frame, config, int(recent_n))
    if active is not None:
        st.sidebar.download_button("Download derived_features.csv", active.to_csv(index=False).encode("utf-8"), file_name="derived_features.csv", mime="text/csv")
    st.divider()
    st.caption("Visualization ≠ Edge · Correlation ≠ Causation · State Classification ≠ Trade Signal · v1.3")
