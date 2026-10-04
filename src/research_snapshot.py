"""Bundled read-only research snapshot for the public web edition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import pandas as pd


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    """Immutable container for the bundled v0.1.2 research outputs."""

    report: dict
    candidate: pd.DataFrame
    validation: pd.DataFrame


_REQUIRED_CANDIDATE_COLUMNS = {
    "Horizon",
    "Non-Overlapping N 12-Month",
    "Mean Forward ATR 12-Month",
    "Median Forward ATR 12-Month",
    "Mean ATR Difference vs Baseline 12-Month",
    "Difference vs Baseline ATR 95% CI Low 12-Month",
    "Difference vs Baseline ATR 95% CI High 12-Month",
    "Tail-Driven Result Warning 12-Month",
}


def load_research_snapshot(app_root: Path | None = None) -> ResearchSnapshot:
    """Load and validate the small, bundled public research snapshot."""

    root = app_root or Path(__file__).resolve().parents[1]
    snapshot_dir = root / "analysis" / "v0.1.2"
    report_path = snapshot_dir / "v0.1.2_12month_report.json"
    candidate_path = snapshot_dir / "candidate_30day_vs_12month.csv"
    validation_path = snapshot_dir / "BTCUSDT_5m_12month_validation_summary.csv"

    missing = [
        str(path.relative_to(root))
        for path in (report_path, candidate_path, validation_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Bundled research snapshot is incomplete: " + ", ".join(missing)
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidate = pd.read_csv(candidate_path)
    validation = pd.read_csv(validation_path)

    absent = sorted(_REQUIRED_CANDIDATE_COLUMNS - set(candidate.columns))
    if absent:
        raise ValueError(
            "Candidate snapshot is missing required columns: " + ", ".join(absent)
        )

    return ResearchSnapshot(
        report=report,
        candidate=candidate,
        validation=validation,
    )
