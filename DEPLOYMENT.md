# Market State Explorer v0.1.3 — Web Deployment

This edition is prepared for a small public Streamlit deployment while retaining
all v0.1.2 quantitative definitions unchanged.

## Recommended first deployment: Streamlit Community Cloud

1. Put this project in a GitHub repository.
2. In Streamlit Community Cloud, create a new app from that repository.
3. Select the repository branch that contains this project.
4. Set the entry point to `app.py`.
5. Select Python 3.12 when the platform offers a Python-version choice.
6. Deploy.

The repository includes `requirements.txt` and `.streamlit/config.toml` so no
manual package list is required.

## What works immediately

The landing page is **Research Snapshot**. It uses only the small files under
`analysis/v0.1.2/`, so the public site is useful before anyone downloads exchange
data. It includes the 12-month BTCUSDT 5m validation snapshot and the pre-specified
High Effort / High Result × Short Covering comparison.

The existing CSV Upload workflow remains available.

The Native Data Builder also remains available, but it is resource-intensive.
Free hosting may sleep, reset local files, or impose CPU/RAM/runtime limits. Start
with about 30 days. For ranges above 31 days the UI requires explicit confirmation.
Always download a built dataset if you want a durable copy; cloud-local cache is
not treated as permanent storage.

## Public deployment safety

- No Binance API key or account credentials are used.
- Raw/processed runtime data remain excluded by `.gitignore`.
- The bundled 12-month research report has local Windows paths removed.
- No authenticated trading or order execution exists.
- The app explicitly states that state classification is not a trading signal.

## Local launch

```bash
python -m pip install -e ".[dev]"
python -m streamlit run app.py
```

## Generic hosting command

A host that provides a `PORT` environment variable can generally launch with:

```bash
python -m streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT
```

Hosting plans and free-tier limits can change. Verify the chosen provider's
current limits before relying on it for long historical builds or persistent
storage.
