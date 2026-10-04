# Market State Explorer v0.1.3 — Web Deployment Edition

Market State Explorer is an interpretable historical research application for
crypto perpetual-futures bars. It separates participation (**Effort**), effective
price displacement (**Result**), and Price/Delta/Open Interest relationships
(**Positioning**), then asks how comparable states behaved over subsequent bars.

The application is descriptive. It does not generate BUY/SELL recommendations,
execute orders, consume live or authenticated account data, or use machine
learning. A clean visual cluster is not evidence of predictive value.


## Web deployment edition

v0.1.3 keeps the v0.1.2 quantitative model unchanged and adds a deployment-safe
public landing experience. **Research Snapshot** is now the default page and uses
the small bundled 12-month validation outputs, so a hosted site is useful without
first downloading exchange archives. The Native Data Builder and CSV upload remain
available. Long Data Builder requests require explicit confirmation because free
hosting may impose runtime, memory, disk, or sleep limits.

Deployment files included in this release:

- `requirements.txt` for simple hosted installation;
- `.streamlit/config.toml` for the dark public UI;
- `.github/workflows/tests.yml` for GitHub test automation;
- `DEPLOYMENT.md` with Streamlit-oriented deployment steps.

No model formula, threshold, event definition, no-lookahead rule, Delta method, or
Open Interest alignment rule changed in v0.1.3.

## Installation and launch

Python 3.12 is required for the validated deployment profile.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
streamlit run app.py
```

On macOS or Linux, activate with `source .venv/bin/activate`.

After installation, historical data building happens inside the existing
Streamlit application. No separate per-dataset terminal command is required.

## Native Data Builder

The **Data Builder** page retains the fixed v0.1.1 scope:

```text
Exchange:  Binance USDT-M
Symbol:    BTCUSDT
Timeframe: 5m
Dates:     inclusive UTC calendar dates
```

Choose a start and end date and select **Build Dataset**. The builder checks the
raw cache, obtains only missing official source periods, validates and preserves
raw archives, reconstructs Delta, aligns Open Interest, runs builder-specific
quality checks, and saves processed CSV and JSON metadata. A dataset marked
`INVALID` cannot be loaded into Explorer. A successful build can be passed
directly to State Map with **Use in Explorer**; CSV upload remains available.

The recommended first run is approximately 30 days, followed by 90 days only
after source semantics and Positioning distributions have been inspected.

### Official data source

The native builder uses only official Binance public data:

- [Binance Data Collection archives](https://data.binance.vision/) are primary.
- [Binance's official public-data repository](https://github.com/binance/binance-public-data)
  documents archive provenance, file schema, publication cadence, and SHA-256
  sidecar checksums.
- [Official USDⓈ-M market-data documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
  defines the kline and Open Interest REST fallbacks.

Daily archive ZIPs and their official `.CHECKSUM` files are cached under
`data/raw/binance/BTCUSDT/`. ZIP structure, CSV schema, and SHA-256 are validated
before use. A corrupted entry is quarantined and never silently trusted. REST
fallback payloads are also cached with a local digest. Raw source files are not
overwritten by processed data.

The official historical Open Interest REST endpoint supports a five-minute
period but explicitly retains only the latest month. The official metrics archive
is therefore the primary historical OI source; REST is a recent-gap fallback. If
official coverage cannot satisfy the requested range, the app reports requested,
available, and missing coverage without silently shortening dates.

### Native Delta

Canonical `volume` is Binance base volume, never quote volume. Delta is derived
from the official taker-buy base-volume field:

```text
aggressive_buy_volume  = taker_buy_base_volume
aggressive_sell_volume = volume - taker_buy_base_volume
delta                  = 2 × taker_buy_base_volume - volume
```

Source rows must satisfy non-negative Volume and Taker Buy Volume,
`Taker Buy <= Volume`, non-negative reconstructed aggressive-sell volume, and
`abs(Delta) <= Volume` within floating-point tolerance. Invalid rows are not
clamped into validity.

### Open Interest field and timestamp semantics

The canonical quantity field is Binance `sumOpenInterest`. The native
`sumOpenInterestValue` field is explicitly excluded because notional OI embeds
price. Binance USDⓈ-M perpetual Open Interest quantity is contracts; BTCUSDT is a
linear contract where 1 contract = 1 BTC, so the audited output is recorded with
native unit `contracts`, output unit `BTC`, and multiplier `1.0`.

Binance documents the historical OI timestamp as the **end time of the period**.
For each candle, alignment selects only the latest OI period end satisfying:

```text
oi_source_timestamp <= canonical_bar_close_timestamp
```

An exact period-end match is allowed. Future backward-fill and interpolation are
prohibited. Default maximum age is 300 seconds; older observations become
explicit `MISSING`. Output preserves `oi_source_timestamp`, `oi_age_seconds`, and
`oi_alignment_quality` (`EXACT`, `RECENT`, `STALE`, or `MISSING`). Any negative
age makes the dataset invalid.

### Builder quality and status

The build report includes expected/received/missing/duplicate klines, Delta
validity, OI source/matched/missing/stale rows, Kline and OI coverage, OI age,
gaps, segments, and future matches. `Future OI Matches` must equal zero.

Research-quality defaults are Kline coverage of at least 99.9% and OI coverage
of at least 99%, with no invalid Delta rows, future OI matches, or duplicate
klines. Lower but usable coverage is visibly marked `USABLE_WITH_WARNINGS`;
critical integrity failures or materially insufficient coverage are `INVALID`.

## Input CSV contract

Required columns:

| Column | Meaning |
|---|---|
| `timestamp` | Bar opening time: ISO-8601, Unix seconds, or Unix milliseconds |
| `open`, `high`, `low`, `close` | Positive OHLC prices with valid bar relationships |
| `volume` | Non-negative total traded quantity |
| `delta` | Aggressive buy volume minus aggressive sell volume |
| `oi` | Positive Open Interest snapshot, preferably at bar close |

Optional `symbol`, `exchange`, and `timeframe` columns are preserved. Delta is
preferably expressed in the same unit as Volume. `abs(delta) > volume` creates a
visible warning rather than automatic rejection because vendor conventions can
differ. OI units may be arbitrary but must be internally consistent within a
continuous dataset.

Internally, timestamps are timezone-aware UTC. The selected display timezone
(Asia/Taipei by default) affects presentation only. Original input data is kept
as a separate raw frame by the loader. Calculation data is sorted by timestamp;
unparseable timestamps and unresolved duplicate timestamps reject the file.
Missing or invalid values are flagged, never forward-filled or interpolated.

## Mathematical model

All normalization uses the historical reference `t-W ... t-1`; the current
observation is excluded.

For a historical window, let `M` be its median and:

```text
MAD = median(abs(x - M))
scale = 1.4826 × MAD
```

If robust scale is below `1e-12`, population standard deviation is used. If both
scales are effectively zero, the normalized value is zero. Scores are clipped to
`[-8, +8]`.

### Effort

```text
effort_raw   = ln(1 + volume)
effort_score = (effort_raw - historical_median) / historical_scale
```

Open Interest and signed Delta are deliberately excluded from Effort.

### Result

True Range is the maximum of current range and the two prior-close gap measures.
ATR uses Wilder smoothing, initialized independently inside each data segment.
The current bar uses `ATR[t-1]`:

```text
displacement           = abs(close - open) / ATR[t-1]
directional_efficiency = abs(close - open) / max(high - low, 1e-12)
result_raw              = displacement × (0.5 + 0.5 × directional_efficiency)
result_score            = centered robust z-score(result_raw)
```

The zero lines create four Effort–Result regions. A separate boundary warning is
set when either score has absolute magnitude below the configured boundary.

### Positioning

```text
price_log_return = ln(close[t] / close[t-1])
delta_ratio      = delta / volume                 (NA when volume is zero)
oi_log_change    = ln(oi[t] / oi[t-1])
```

These signed quantities use historical data only to estimate scale. Their actual
zero remains the directional center: `zero_score = value / historical_scale`.
Each becomes +1, 0, or -1 at the configured significance threshold. A canonical
Positioning State is assigned only when all three components are significant;
otherwise it is `Mixed / Low Conviction`.

## Gaps and no-lookahead architecture

The expected interval is the median positive timestamp difference. An interval
greater than `1.5 × expected` starts a new `segment_id`. ATR and rolling
normalization restart within that segment; no window bridges the gap.

State calculation and validation are separate:

```text
data through t → state features at t
data after t   → validation outcomes only
```

The implementation shifts every normalization source before rolling. ATR is also
shifted before Result uses it. Tests mutate future observations and verify that
historical state features remain identical. Forward outcomes are calculated only
inside `src.validation` and never flow back to `src.features`.

## Historical validation

For each configured horizon, validation reports log forward return, basis points,
ATR-normalized return, maximum favorable excursion, and maximum adverse
excursion. Explicit bullish and bearish hypothesis events also report
direction-oriented outcomes.

Groups include:

- each Effort–Result region;
- each Positioning State;
- Region × Positioning State combinations;
- LEHR Short Pressure, LEHR Long Pressure, and HELR events.

Raw counts and horizon-de-overlapped counts are both retained. With the default
`Non-Overlapping = True`, selecting an observation skips the following `H` bars
for the same group. The unconditional baseline uses the same horizon-based
sampling convention, so conditional and baseline comparisons are like-for-like.

The table includes mean/median outcomes, positive rates, excursion probabilities,
baseline differences, a Wilson 95% interval for the win rate, and a deterministic
bootstrap 95% interval for mean forward log return (seed 42 by default).

v0.1.2 hardened interpretation without changing any state, event, forward-outcome,
threshold, or non-overlapping sampling definition:

- `Forward Return 95% CI Low/High` explicitly names the existing conditional
  mean log-return interval. Legacy `95% CI Low/High` columns remain identical for
  CSV backward compatibility.
- `Difference vs Baseline ATR 95% CI Low/High` is a separate deterministic
  bootstrap interval for Conditional Mean Forward ATR minus Baseline Mean ATR.
  Conditional and baseline means are independently resampled; the baseline
  bootstrap distribution is reused within each horizon.
- `Forward ATR 25th/50th/75th Percentile` exposes the central distribution rather
  than relying only on its arithmetic mean.
- `Event Frequency %` is the raw research-event count divided by all valid
  forward-outcome opportunities for that horizon. `Positioning State Frequency %`
  reports the corresponding marginal state frequency. These prevalence measures
  are intentionally calculated before de-overlapping; outcome statistics continue
  to honor the **Non-Overlapping** toggle.
- `Mean vs Median Divergence Warning` is raised when the mean/median distance is
  greater than half the interquartile range. `Tail-Driven Result Warning` is raised
  when the mean falls outside the 25th–75th percentile interval or has a different
  sign from the median. These are transparent distribution diagnostics, not model
  thresholds or optimized signal rules.

Confidence intervals and warnings are not labeled as statistical significance.
They are safeguards against over-interpreting noisy, imbalanced, or tail-driven
conditional samples.

The release audit, including the exact v0.1.1 30-day comparison and the fixed-scope
12-month run, is recorded in
[`analysis/v0.1.2/VALIDATION_HARDENING_REPORT.md`](analysis/v0.1.2/VALIDATION_HARDENING_REPORT.md).

Sample labels are intentionally conservative:

- fewer than 30: `Insufficient sample`;
- 30–99: `Exploratory`;
- 100 or more: `Usable research sample`.

## Interface and exports

The sidebar controls optional CSV upload, timezone, ATR and normalization
settings, significance/boundary thresholds, trail/history lengths, horizons, and
advanced event thresholds. Pages cover Data Builder, State Map, Trajectory,
Validation, and Data Quality. The app exports the native dataset, metadata JSON,
`derived_features.csv`, and `validation_summary.csv`.

Run tests with:

```bash
pytest
```

## Limitations and roadmap

v0.1.2 intentionally omits funding, liquidations, session structure, VWAP,
POC/VAH/VAL, higher-timeframe structure, order-book liquidity, exchange-specific
behavior, cross-exchange OI, regime-conditioned normalization, time-of-day
seasonality, and volatility-regime conditioning. It also omits live websockets,
authenticated APIs, other symbols/exchanges/timeframes, automation, ML,
clustering, PCA/UMAP, and rotatable 3D.

Official Binance archives may contain gaps or duplicates, and daily files arrive
after the trading day. The builder exposes these conditions rather than repairing
them with resampling or interpolation. Official archive or one-month REST OI
availability may limit the maximum usable request.

A possible v0.2 may explore session-aware normalization, funding, liquidations,
value-area context, transition matrices, conditional transition probabilities,
or historical analogue search. A third visual dimension is gated on v0.1
validation and must be mathematically justified rather than invented.

**Visualization ≠ Edge. Correlation ≠ Causation. State Classification ≠ Trade Signal.**
