# Market State Explorer v1.0 — Production Web Edition

v1.0 turns the research preview into a self-contained public research dashboard suitable for free Streamlit hosting.

## Production additions

- Official Binance USDⓈ-M recent-data mode with no API key.
- Five-minute shared cache to reduce repeated public-source traffic.
- Only completed 5m bars are admitted; the still-open bar is excluded with a safety lag.
- Delta remains reconstructed from official taker-buy base volume.
- Open Interest remains strictly backward aligned; future OI matches are surfaced in Data Quality.
- Live Dashboard, State Map, Trajectory, Validation, Data Quality, Methodology, and CSV upload are unified in one app.
- Active datasets validate 5 / 10 / 15 / 20 / 30 / 60 bars.
- The frozen 12-month benchmark remains honestly limited to the 5 / 10 / 20 horizons originally computed.
- Public-site upload/resource caps protect free hosting.
- GitHub Actions CI added for Python 3.12 compile + tests.

## Model lock

No v0.1.2 Effort, Result, Positioning, normalization, Delta reconstruction, or OI-alignment mathematics were changed for v1.0.

## Interpretation

The application remains descriptive research software. State labels, confidence intervals, historical forward distributions, and live classifications are not BUY/SELL instructions and do not establish causality.
