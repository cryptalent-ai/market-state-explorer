# Market State Explorer v0.1.4 — Interactive Web Edition

v0.1.4 turns the first public Streamlit preview into an interactive research site while keeping the v0.1.2 quantitative model unchanged.

## Added

- Interactive Effort × Result State Map for uploaded research CSVs.
- Interactive State Trajectory for uploaded research CSVs.
- Bundled 12-month BTCUSDT 5m validation core with filtering by horizon, validation group, sample quality, and text search.
- Validation comparison chart using Mean Forward ATR minus Baseline Mean ATR.
- Dynamic forward validation for uploaded datasets.
- Data-quality page for uploaded datasets.
- Downloadable filtered validation and derived-feature CSVs.
- Cleaner public-web navigation and fixed audited model defaults.

## Public-hosting design

The 105,120-bar raw research dataset is intentionally not bundled in the public repository. The website ships an audited 12-month validation snapshot and lets a user upload a valid research CSV for State Map, Trajectory, and custom validation. This keeps the free Streamlit deployment lightweight and avoids repeatedly downloading large Binance archives on shared hosting.

## Unchanged

- Effort formula and robust normalization.
- Result formula and ATR reference behavior.
- Positioning classification.
- Research-event definitions and thresholds.
- Forward-return, MFE/MAE, baseline, bootstrap, and non-overlap logic.
- Delta reconstruction and OI semantics in the research engine.

The application remains a research instrument, not a trading-signal or execution system.
