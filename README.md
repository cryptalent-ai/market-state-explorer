# Market State Explorer v1.0 — Production Web Edition

Market State Explorer is an interpretable BTCUSDT 5-minute research dashboard built around three ideas:

- **Effort** — how unusual current participation is versus its recent history;
- **Result** — how efficiently price actually displaced relative to ATR;
- **Positioning** — how Price, Delta, and Open Interest line up.

The app is descriptive research software. It does **not** generate BUY/SELL instructions, place orders, use authenticated account data, or claim causality.

## What v1.0 provides

The public Streamlit app combines:

- a **Live Binance** mode using official Binance USDⓈ-M public data with no API key;
- a **Dashboard** with the latest completed market state;
- **State Map** and **Trajectory** views;
- **Historical Forward Validation**;
- **Data Quality** and official-source audit information;
- **CSV upload** for your own compatible research data;
- the frozen **12-month audited BTCUSDT 5m benchmark** from v0.1.2.

Live mode uses a recent eight-day window, caches public-source data for five minutes, excludes the still-open 5m bar with a safety lag, reconstructs Delta from official taker-buy base volume, and aligns Open Interest strictly backward so future OI is never used for an earlier bar.

## Validation horizons

Active datasets are evaluated at:

```text
5 / 10 / 15 / 20 / 30 / 60 bars
```

For BTCUSDT 5m this corresponds to approximately:

```text
25 / 50 / 75 / 100 / 150 / 300 minutes
```

The bundled 12-month audited snapshot intentionally remains limited to **5 / 10 / 20** because those were the horizons actually computed when that benchmark was frozen. v1.0 does not interpolate or fabricate 15/30/60 results for it.

## Core model lock

v1.0 preserves the audited v0.1.2 model mathematics. It does not change the existing Effort, Result, Positioning, normalization, Delta reconstruction, OI alignment, event definitions, or no-lookahead architecture.

### Effort

```text
effort_raw   = ln(1 + volume)
effort_score = robust historical z-score(effort_raw)
```

### Result

```text
displacement           = abs(close - open) / ATR[t-1]
directional_efficiency = abs(close - open) / max(high - low, 1e-12)
result_raw              = displacement × (0.5 + 0.5 × directional_efficiency)
result_score            = robust historical z-score(result_raw)
```

### Positioning

The model robustly normalizes signed:

```text
price_log_return = ln(close[t] / close[t-1])
delta_ratio      = delta / volume
oi_log_change    = ln(oi[t] / oi[t-1])
```

and classifies only sufficiently significant combinations. Ambiguous combinations remain **Mixed / Low Conviction**.

## Live-data safeguards

The production live path uses only official Binance public sources. Important rules:

- only completed five-minute candles are admitted;
- the current still-open bar is excluded;
- Delta is reconstructed from official taker-buy base volume;
- Open Interest is quantity-based and strictly backward aligned;
- future OI matches are surfaced in Data Quality and must remain zero;
- recent data are cached for five minutes to reduce repeated source traffic on free hosting;
- live-source failures fail soft instead of crashing the whole research site.

Live validation is intentionally labeled exploratory because the live window is short. Use the bundled 12-month benchmark or a longer uploaded dataset for research conclusions.

## Input CSV contract

Required columns:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601, Unix seconds, or Unix milliseconds |
| `open`, `high`, `low`, `close` | OHLC prices |
| `volume` | total traded quantity |
| `delta` | aggressive buy volume minus aggressive sell volume |
| `oi` | Open Interest quantity |

The public site limits uploads to 60 MB and 150,000 rows to protect free-host resources.

## Historical validation

Validation reports sample size and forward behavior by Effort–Result region, Positioning State, Region × Positioning, and research events. Hardened v0.1.2 outputs include:

- Mean / Median Forward ATR;
- Forward ATR 25th / 50th / 75th percentiles;
- Positive Rate;
- MFE and MAE probabilities;
- Baseline Mean ATR;
- Mean ATR Difference vs Baseline;
- Difference vs Baseline 95% CI;
- Mean-vs-Median divergence warning;
- Tail-driven result warning;
- conservative sample-quality labels.

Non-overlapping sampling is available so overlapping forward windows are not treated as independent observations.

## Installation

Python 3.12 is the supported deployment profile.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
streamlit run app.py
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Automated verification

GitHub Actions runs on pull requests and on pushes to `main` using Python 3.12. It installs the project, compiles `app.py`, `src`, and `tests`, then runs the full pytest suite.

The v1.0 live-data tests specifically verify that the current unfinished bar is excluded and that future Open Interest is never matched backward into the dataset.

## Deployment

For Streamlit Community Cloud:

```text
Repository: cryptalent-ai/market-state-explorer
Branch:     main
Main file:  app.py
Python:     3.12
```

See `RELEASE_NOTES_v1.0.md` for the production-release summary.

## Interpretation guardrail

**Visualization ≠ Edge. Correlation ≠ Causation. State Classification ≠ Trade Signal.**
