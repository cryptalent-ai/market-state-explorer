"""Public GitHub issue-comment relay for near-real-time market-state snapshots."""
from __future__ import annotations

import base64
import json
import re
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pandas as pd
import requests

RELAY_SCHEMA = "market-state-relay/v1"
RELAY_MARKER = "<!-- MARKET_STATE_RELAY_V1 -->"
RELAY_REPO = "cryptalent-ai/market-state-explorer"
RELAY_ISSUE_NUMBER = 5
RELAY_COMMENT_ID = 5983131268
RELAY_COMMENT_API = (
    f"https://api.github.com/repos/{RELAY_REPO}/issues/comments/{RELAY_COMMENT_ID}"
)
RELAY_COMMENT_URL = (
    f"https://github.com/{RELAY_REPO}/issues/{RELAY_ISSUE_NUMBER}#issuecomment-{RELAY_COMMENT_ID}"
)
RELAY_FRESH_SECONDS = 15 * 60
RELAY_MAX_COMMENT_CHARS = 60_000
RELAY_MAX_ROWS = 500

RELAY_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "delta",
    "delta_ratio",
    "oi",
    "oi_log_change",
    "effort_raw",
    "effort_score",
    "result_raw",
    "result_score",
    "directional_efficiency",
    "price_significance",
    "delta_significance",
    "oi_significance",
    "positioning_state",
    "effort_result_region",
    "state_strength",
    "state_velocity",
    "bar_direction",
    "lehr_short_pressure",
    "lehr_long_pressure",
    "helr_event",
    "near_state_boundary",
    "data_quality_flag",
)


@dataclass(slots=True)
class RelayMetadata:
    source: str
    updated_at_utc: str
    completed_through_utc: str
    rows: int
    oi_coverage: float
    future_oi_matches: int
    age_seconds: float
    fresh: bool
    comment_url: str = RELAY_COMMENT_URL
    # Preserve the existing age_seconds publication-age field and constructor.
    market_data_age_seconds: float | None = None
    publication_fresh: bool | None = None
    market_data_fresh: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now(now: datetime | pd.Timestamp | None = None) -> pd.Timestamp:
    ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def completed_through_age_seconds(value: str, *, now: datetime | pd.Timestamp | None = None) -> float:
    """Age of the completed 5m close boundary, not the last bar's open time.

    Missing/invalid/future boundaries fail closed. Naive legacy timestamps are
    interpreted as UTC, consistently with the existing publication parser.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Relay completed-through timestamp is missing or invalid.")
    try:
        completed = pd.Timestamp(value)
        if pd.isna(completed):
            raise ValueError("NaT")
        completed = completed.tz_localize("UTC") if completed.tzinfo is None else completed.tz_convert("UTC")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Relay completed-through timestamp is invalid.") from error
    age = (_utc_now(now) - completed).total_seconds()
    if age < 0:
        raise ValueError("Relay completed-through timestamp is in the future.")
    return float(age)


def _compact_frame(frame: pd.DataFrame, rows: int) -> pd.DataFrame:
    missing = [column for column in RELAY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("Relay frame is missing columns: " + ", ".join(missing))
    compact = frame.loc[:, RELAY_COLUMNS].tail(rows).copy()
    compact["timestamp"] = pd.to_datetime(compact["timestamp"], utc=True)
    return compact


def build_relay_comment(
    derived: pd.DataFrame,
    *,
    source: str,
    completed_through_utc: str,
    oi_coverage: float,
    future_oi_matches: int,
    updated_at: datetime | pd.Timestamp | None = None,
) -> str:
    """Encode a bounded compressed snapshot suitable for one public issue comment."""

    updated = _utc_now(updated_at)
    rows = min(RELAY_MAX_ROWS, len(derived))
    while rows >= 25:
        compact = _compact_frame(derived, rows)
        raw = compact.to_json(
            orient="split",
            date_format="iso",
            double_precision=8,
        ).encode("utf-8")
        packed = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        envelope = {
            "schema": RELAY_SCHEMA,
            "status": "ok",
            "updated_at_utc": updated.isoformat(),
            "completed_through_utc": str(completed_through_utc),
            "rows": len(compact),
            "oi_coverage": float(oi_coverage),
            "future_oi_matches": int(future_oi_matches),
            "source": str(source),
            "encoding": "zlib+base64+pandas-split-json",
            "data": packed,
        }
        body = (
            f"{RELAY_MARKER}\n```json\n"
            + json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
            + "\n```"
        )
        if len(body) <= RELAY_MAX_COMMENT_CHARS:
            return body
        rows //= 2
    raise ValueError("Relay payload could not be reduced below the GitHub comment limit.")


def parse_relay_comment(
    body: str,
    *,
    now: datetime | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, RelayMetadata]:
    """Decode and validate one relay comment body."""

    if RELAY_MARKER not in body:
        raise ValueError("Relay marker is missing.")
    match = re.search(r"```json\s*(\{.*\})\s*```", body, flags=re.DOTALL)
    if not match:
        raise ValueError("Relay JSON block is missing.")
    envelope = json.loads(match.group(1))
    if envelope.get("schema") != RELAY_SCHEMA or envelope.get("status") != "ok":
        raise ValueError("Relay is not initialized with a usable payload.")
    if envelope.get("encoding") != "zlib+base64+pandas-split-json":
        raise ValueError("Relay encoding is unsupported.")

    packed = base64.b64decode(str(envelope["data"]), validate=True)
    raw = zlib.decompress(packed).decode("utf-8")
    frame = pd.read_json(StringIO(raw), orient="split")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")

    updated = pd.Timestamp(envelope["updated_at_utc"])
    updated = updated.tz_localize("UTC") if updated.tzinfo is None else updated.tz_convert("UTC")
    clock = _utc_now(now)
    age = max(0.0, (clock - updated).total_seconds())
    completed_through = envelope.get("completed_through_utc")
    market_age = completed_through_age_seconds(completed_through, now=clock)
    publication_fresh = age <= RELAY_FRESH_SECONDS
    market_data_fresh = market_age <= RELAY_FRESH_SECONDS
    metadata = RelayMetadata(
        source=str(envelope.get("source", "Local relay")),
        updated_at_utc=updated.isoformat(),
        completed_through_utc=completed_through,
        rows=int(envelope.get("rows", len(frame))),
        oi_coverage=float(envelope.get("oi_coverage", 0.0)),
        future_oi_matches=int(envelope.get("future_oi_matches", 0)),
        age_seconds=age,
        fresh=publication_fresh and market_data_fresh,
        market_data_age_seconds=market_age,
        publication_fresh=publication_fresh,
        market_data_fresh=market_data_fresh,
    )
    if metadata.future_oi_matches != 0:
        raise ValueError("Relay payload reports future OI matches and was rejected.")
    return frame, metadata


def fetch_public_relay(
    *,
    timeout_seconds: float = 10.0,
    now: datetime | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, RelayMetadata]:
    """Fetch the public relay comment without any GitHub token."""

    response = requests.get(
        RELAY_COMMENT_API,
        timeout=timeout_seconds,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Market-State-Explorer/1.1",
        },
    )
    response.raise_for_status()
    payload = response.json()
    return parse_relay_comment(str(payload["body"]), now=now)
