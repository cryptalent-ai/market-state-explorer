# Market State Explorer v0.1.5 — Horizon Expansion Edition

This release expands forward-validation horizons without changing the audited market-state mathematics.

## What changed

- New/recomputed validation now evaluates `5 / 10 / 15 / 20 / 30 / 60` bars.
- For BTCUSDT 5m these correspond to approximately `25 / 50 / 75 / 100 / 150 / 300` minutes.
- Dashboard candidate charts use categorical x-axis ticks so only horizons that actually exist in the bundled snapshot are shown.
- The bundled 12-month snapshot remains the original audited `5 / 10 / 20` result set. `15 / 30 / 60` are never interpolated or fabricated.
- Uploaded research datasets can be recomputed across all six horizons.
- Validation tables tolerate compact bundled snapshots that omit optional columns such as MFE/MAE.

## What did not change

- Effort mathematics
- Result mathematics
- Positioning states and thresholds
- Research Event definitions
- Delta reconstruction
- Open Interest alignment
- Past-only normalization
- Non-overlapping validation option

## Research note

Adding more horizons increases the number of comparisons. Treat the expanded horizon set as a fixed research grid and avoid selecting a horizon only because it produced the most attractive historical result.
