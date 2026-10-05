import platform
import sys
import time

import streamlit as st

st.set_page_config(page_title="MSE v1.3 Cloud Probe", layout="wide")
st.title("Market State Explorer v1.3 — Cloud Probe")
st.success("Streamlit process started successfully.")
st.write({
    "python": sys.version,
    "platform": platform.platform(),
    "streamlit": st.__version__,
})


def checkpoint(label, func):
    start = time.perf_counter()
    try:
        value = func()
        elapsed = time.perf_counter() - start
        st.success(f"{label}: OK ({elapsed:.2f}s)")
        return value
    except Exception as exc:
        elapsed = time.perf_counter() - start
        st.error(f"{label}: FAILED after {elapsed:.2f}s — {type(exc).__name__}: {exc}")
        return None


st.subheader("Startup isolation")

modules = checkpoint(
    "Import v1.3 application modules",
    lambda: __import__("src.web_app_v13", fromlist=["*"]),
)

snapshot = relay = None
if modules is not None:
    snapshot = checkpoint("Load bundled research snapshot", modules.load_snapshot)
    relay = checkpoint("Load public Relay payload", modules.load_relay_dataset)

    if snapshot is not None:
        report, candidate, validation = snapshot
        st.write({
            "snapshot_candidate_rows": len(candidate),
            "snapshot_validation_rows": len(validation),
        })

    if relay is not None:
        relay_frame, relay_meta = relay
        st.write({
            "relay_rows": len(relay_frame),
            "relay_fresh": bool(relay_meta.fresh),
            "relay_age_seconds": float(relay_meta.age_seconds),
            "relay_completed_through_utc": str(relay_meta.completed_through_utc),
        })

if modules is not None and snapshot is not None and relay is not None:
    st.subheader("Dashboard component isolation")
    report, candidate, validation = snapshot
    relay_frame, relay_meta = relay

    frame = checkpoint(
        "Prepare Relay state frame",
        lambda: modules.prepare_state_frame(relay_frame),
    )

    if frame is not None and not frame.empty:
        config = checkpoint(
            "Build v1.3 display config",
            lambda: modules.ModelConfig(
                display_timezone="Asia/Taipei",
                display_history=500,
                trail_length=12,
                forward_horizons=modules.WEB_FORWARD_HORIZONS,
            ),
        )

        if config is not None:
            checkpoint(
                "Compute recent-state summary",
                lambda: modules.compute_recent_state_summary(frame, 12),
            )
            checkpoint(
                "Compute current-state rarity",
                lambda: modules.compute_state_rarity(frame, 500),
            )
            checkpoint(
                "Match current historical validation",
                lambda: modules.match_current_validation_rows(frame.iloc[-1], validation),
            )

            matrix = checkpoint(
                "Build State Matrix figure",
                lambda: modules.state_matrix_figure(frame, 500, 12),
            )
            if matrix is not None:
                checkpoint("Serialize State Matrix figure", matrix.to_json)

            ribbon = checkpoint(
                "Build Timeline Ribbon figure",
                lambda: modules.timeline_ribbon_figure(frame, 12, "Asia/Taipei"),
            )
            if ribbon is not None:
                checkpoint("Serialize Timeline Ribbon figure", ribbon.to_json)

            st.subheader("Live render isolation")
            checkpoint(
                "Render source status",
                lambda: modules._source_status(relay_meta, "Near-real-time local relay", None),
            )
            checkpoint(
                "Render current-state cards",
                lambda: modules.render_current_state(frame, "Asia/Taipei"),
            )
            checkpoint(
                "Render seven-question decision strip",
                lambda: modules._decision_strip(frame, 500, 12, validation),
            )
            if matrix is not None:
                checkpoint("Render State Matrix chart", lambda: modules._plot(matrix))
            checkpoint(
                "Render Timeline Ribbon section",
                lambda: modules.render_ribbon(frame, 12, "Asia/Taipei"),
            )
            checkpoint(
                "Render recent-state summary",
                lambda: modules.render_recent_summary(frame, 12),
            )
            checkpoint(
                "Render recent 5-state table",
                lambda: modules.render_recent_table(frame, "Asia/Taipei"),
            )
            checkpoint(
                "Render validation snapshot",
                lambda: modules.render_validation_snapshot(frame.iloc[-1], validation),
            )

            st.success("All isolated v1.3 Dashboard stages completed.")

st.caption(
    "Diagnostic only. This probe isolates the production Dashboard stages without running the full sidebar/navigation orchestration or Binance archive fallback."
)
