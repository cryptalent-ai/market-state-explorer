from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.test_state_views import validation_rows


def snapshot_page(current, validation):
    from src.web_app_v13 import render_validation_snapshot
    render_validation_snapshot(current, validation)


@pytest.mark.parametrize("quality", ["Usable research sample", "Exploratory", "Insufficient sample"])
def test_snapshot_quality_labels_and_warnings(derived, quality):
    current = derived.iloc[-1]
    validation = validation_rows(current.effort_result_region, current.positioning_state, (quality,)*3)
    app = AppTest.from_function(snapshot_page, args=(current, validation)).run(timeout=15)
    assert not app.exception
    assert any(quality in m.value for m in app.markdown)
    warnings = [w.value for w in app.warning]
    assert bool(warnings) == (quality == "Insufficient sample")


def test_snapshot_no_match_reports_limitation(derived):
    app = AppTest.from_function(snapshot_page, args=(derived.iloc[-1], pd.DataFrame())).run(timeout=15)
    assert not app.exception
    assert any("No sufficiently matched historical validation sample" in w.value for w in app.warning)


def test_bundled_snapshot_uses_published_median(derived):
    current = derived.iloc[-1]
    validation = validation_rows(current.effort_result_region, current.positioning_state).drop(columns="Median Forward ATR")
    validation["Forward ATR 50th Percentile"] = "0.125"
    app = AppTest.from_function(snapshot_page, args=(current, validation)).run(timeout=15)
    assert not app.exception
    assert any("0.125" in m.value for m in app.markdown)


def test_streamlit_server_startup_health():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true"],
        cwd=Path(__file__).parents[1], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert process.poll() is None, "Streamlit exited before becoming healthy"
            try:
                with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                    assert response.status == 200
                    return
            except (URLError, TimeoutError, ConnectionError):
                time.sleep(.2)
        pytest.fail("Streamlit startup health check timed out")
    finally:
        process.terminate()
        process.wait(timeout=10)
