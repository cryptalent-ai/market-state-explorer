# Market State Explorer v1.1 — Near-Real-Time Relay Edition

Market State Explorer is an interpretable BTCUSDT 5-minute research dashboard built around three ideas:

- **Effort** — how unusual current participation is versus its recent history;
- **Result** — how efficiently price actually displaced relative to ATR;
- **Positioning** — how Price, Delta, and Open Interest line up.

The app is descriptive research software. It does **not** generate BUY/SELL instructions, place orders, use authenticated trading-account data, or claim causality.

## What v1.1 adds

Streamlit Cloud may receive Binance Futures HTTP 451 because the hosted server is in a restricted region. v1.1 solves the freshness problem without using a proxy, VPN, or geo-bypass.

A lightweight **Local Relay** can run on the user's own Binance-accessible Windows machine. Every five minutes it:

1. fetches official Binance USDⓈ-M public market data locally;
2. excludes the still-open 5m bar;
3. reconstructs Delta from taker-buy base volume;
4. aligns Open Interest strictly backward;
5. computes the unchanged audited Market State features locally;
6. publishes only a compact compressed **derived-state snapshot** to one public GitHub issue comment.

The public Streamlit site reads that comment without any secret. If no successful relay update arrives for 15 minutes, it is considered stale and is not presented as current.

The public relay target is GitHub issue **#5** in this repository. It contains public derived market data only. Never place API keys, passwords, account information, or tokens in that issue.

## Automatic source priority

The default website source is:

```text
Auto (Relay → Archive)
```

Behavior:

```text
Fresh Local Relay available
    → use near-real-time derived Market State

Relay missing or stale
    → use Binance hosted source
    → if Binance Futures REST returns HTTP 451, use official delayed daily archives
```

The hosted archive fallback is always labelled as delayed and is never presented as the current market state.

## One-time Windows relay setup

Requirements: Windows, Python 3.12, internet access, and a GitHub account with write access to this repository.

Open PowerShell and run the installer from the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_relay.ps1
```

The installer:

- checks Python 3.12;
- installs GitHub CLI with `winget` if needed;
- opens GitHub's normal browser authorization flow if `gh` is not already authenticated;
- downloads the current `main` branch into `%LOCALAPPDATA%\MarketStateExplorerRelay`;
- creates an isolated Python virtual environment;
- performs one real relay publish test;
- creates a Windows Scheduled Task named `MarketStateExplorerRelay` that runs every five minutes.

To remove the task later:

```powershell
schtasks /Delete /TN MarketStateExplorerRelay /F
```

The local publisher is `scripts/publish_live_relay.py`.

## Existing production features

The public Streamlit app also provides:

- **Dashboard** with the latest accepted market state;
- **State Map** and **Trajectory**;
- **Historical Forward Validation**;
- **Data Quality** and source/relay audit information;
- **CSV upload** for compatible research data;
- the frozen **12-month audited BTCUSDT 5m benchmark** from v0.1.2;
- Binance official delayed archive fallback for hosts where Futures REST returns HTTP 451.

## Validation horizons

Sufficiently long active datasets are evaluated at:

```text
5 / 10 / 15 / 20 / 30 / 60 bars
```

For BTCUSDT 5m this corresponds to approximately:

```text
25 / 50 / 75 / 100 / 150 / 300 minutes
```

The compact near-real-time relay is intentionally **not** used for forward-validation claims. It exists for Current State, State Map, and Trajectory. The bundled 12-month audited snapshot remains limited to **5 / 10 / 20** because those were the horizons actually computed when that benchmark was frozen.

## Core model lock

v1.1 preserves the audited v0.1.2 model mathematics. It does not change Effort, Result, Positioning, normalization, Delta reconstruction, OI alignment, event definitions, or the no-lookahead architecture.

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

## Data safeguards

Important rules:

- only completed five-minute candles are admitted;
- the still-open bar is excluded;
- Delta is reconstructed from official taker-buy base volume;
- Open Interest is quantity-based and strictly backward aligned;
- future OI matches must remain zero;
- relay data are rejected as current after 15 minutes without a successful update;
- the relay publisher refuses to publish if its own machine also falls back to delayed hosted archive data;
- the public relay transports derived/public market data only, not account data or credentials.

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

## Local development

Python 3.12 is the supported profile.

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

GitHub Actions runs on pull requests and pushes to `main` using Python 3.12. It compiles `app.py`, `src`, and `tests`, then runs the pytest suite. Relay tests verify compressed round-trip decoding, the 15-minute freshness rule, and rejection of future OI matches.

## Streamlit deployment

```text
Repository: cryptalent-ai/market-state-explorer
Branch:     main
Main file:  app.py
Python:     3.12
```

## Interpretation guardrail

**Visualization ≠ Edge. Correlation ≠ Causation. State Classification ≠ Trade Signal.**
