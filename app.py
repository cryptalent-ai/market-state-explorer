"""Market State Explorer v1.2.1 — Visual Clarity Hotfix."""
from __future__ import annotations

import importlib
import sys

from src import charts_v12

# Streamlit can hot-reload the page module while retaining an older imported
# ``src.charts`` module in memory. Pin the v1.2 UI to a versioned chart module
# and reload the page module so its function bindings cannot point at v1.1
# signatures.
sys.modules["src.charts"] = charts_v12
import src.web_app_v12 as web_app_v12

importlib.reload(web_app_v12)
web_app_v12.run()
