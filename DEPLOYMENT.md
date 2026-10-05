# v1.3 isolated preview deployment

Do not change the existing production app's branch or settings. Do not merge
`v1.3-decision-ui` into `main` before user acceptance.

## Streamlit Community Cloud preview

Create a **separate** app (not a redeploy of production), using:

| Setting | Value |
| --- | --- |
| Repository | `cryptalent-ai/market-state-explorer` |
| Branch | `v1.3-decision-ui` |
| Entry point | `app.py` |
| Python | `3.12` |
| Dependency file | existing `requirements.txt` |
| Theme | existing `.streamlit/config.toml` |

Choose a separate preview URL. No secrets, Binance account or API keys are
required. The preview reads the existing public Relay; it never publishes or
reconfigures it. Auto source priority is unchanged. Fresh Relay is green; stale
Relay is rejected; HTTP 451 uses official delayed archives with a warning. Upload
CSV and the full Validation page remain available.

Cloud deployment itself requires the account owner's deploy action; a successful
local startup and CI do not certify a running Community Cloud deployment.

## Local preview (Python 3.12)

```bash
git clone --branch v1.3-decision-ui https://github.com/cryptalent-ai/market-state-explorer.git
cd market-state-explorer
python -m venv .venv
```

Activate `.venv` using your shell, then:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m streamlit run app.py --server.port=8513
```

Open `http://localhost:8513`. If editing imported modules during development,
restart the local preview process to verify a clean import; no hot-reload module
alias is used. A fresh branch deployment starts with clean versioned imports.

## Human acceptance checklist

On Dashboard, without opening scatter, answer within 3–5 seconds:

1. Current/latest full Region.
2. Full Positioning State.
3. Dominant Region in recent 12 valid states (ties explicitly labelled).
4. Region/Positioning changes versus adjacent-step count.
5. Current Region's visible-history frequency and relative frequency rank.
6. Existing near-zero-boundary flag.
7. Historical validation quality, N and matched scope per horizon.

Then verify State Map starts with matrix/occupancy/percentiles; Trajectory starts
with timeline/time series/transitions; both legacy 2D views are collapsed under
Advanced. Check full labels at laptop width and timestamps increasing toward the
right. Confirm delayed archives are NOT described as current market data.

Do not infer trading edge from this UI. Sample quality belongs to the historical
benchmark and its matched scope, not to the Relay's compact observation window.
