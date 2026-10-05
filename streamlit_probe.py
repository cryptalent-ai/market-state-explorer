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

st.caption("Diagnostic only. It does not run the full v1.3 page layout or Binance archive fallback.")
