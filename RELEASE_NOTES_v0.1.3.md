# v0.1.3 — Web Deployment Edition

This release converts the existing Streamlit research tool into a deployment-ready
public web edition without changing the v0.1.2 quantitative model.

## Added

- Public **Research Snapshot** landing page with the bundled 12-month BTCUSDT 5m
  validation summary.
- 30-day vs 12-month candidate stability chart for **High Effort / High Result ×
  Short Covering**.
- Public **Methodology** page.
- Free-hosting warnings around long Native Data Builder requests and an explicit
  confirmation for ranges above 31 days.
- `requirements.txt`, `.python-version`, `.streamlit/config.toml`, GitHub Actions
  test workflow, and `DEPLOYMENT.md`.
- Local Windows paths removed from the bundled research report.

## Preserved

- Effort, Result, Positioning, research-event, validation, no-lookahead, Delta,
  and Open Interest alignment definitions are unchanged.
- Native Binance Data Builder remains available.
- CSV upload remains available.

## Verification in this build environment

- Python syntax/compile check passed for `app.py`, `src/`, and `tests/`.
- Snapshot loader and Plotly comparison figure were executed and serialized.
- All non-Streamlit tests except the pre-existing strict digest test passed in the
  current Python 3.13 sandbox. The same digest test also fails on the untouched
  v0.1.2 ZIP in this sandbox, so it is not a v0.1.3 regression. The release pins
  the validated deployment profile to Python 3.12.
- Streamlit itself is not installed in this offline build sandbox, so the
  Streamlit AppTest could not be executed here. The project retains its app test
  for normal Python 3.12 environments.
