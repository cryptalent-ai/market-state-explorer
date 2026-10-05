import platform
import sys

import streamlit as st

st.set_page_config(page_title="MSE v1.3 Cloud Probe", layout="wide")
st.title("Market State Explorer v1.3 — Cloud Probe")
st.success("Streamlit process started successfully.")
st.write({
    "python": sys.version,
    "platform": platform.platform(),
    "streamlit": st.__version__,
})
st.caption("Diagnostic only. This file does not load market data, Relay, Plotly, or the v1.3 application.")
