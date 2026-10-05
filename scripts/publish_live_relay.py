"""Publish a near-real-time derived market-state snapshot from a local machine.

This script is intended to run on a machine where Binance USDⓈ-M public REST is
legally accessible. It does not use a proxy, VPN, or geo-bypass. The published
GitHub issue comment contains only derived/public market data and no secrets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from src.config import ModelConfig
from src.features import build_derived_features
from src.live_data import DEFAULT_HISTORY_DAYS, build_recent_market_data
from src.relay import (
    RELAY_COMMENT_ID, RELAY_REPO, RELAY_FRESH_SECONDS, _utc_now,
    build_relay_comment, completed_through_age_seconds, parse_relay_comment,
)

CACHE_ROOT = Path.home() / ".market-state-explorer" / "cache"


def _find_gh() -> str:
    """Locate GitHub CLI reliably in interactive shells and Windows scheduled tasks."""

    configured = os.environ.get("MARKET_STATE_GH")
    if configured and Path(configured).is_file():
        return configured

    on_path = shutil.which("gh")
    if on_path:
        return on_path

    candidates = []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "GitHub CLI" / "gh.exe")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.extend(
            [
                Path(local_appdata) / "Programs" / "GitHub CLI" / "gh.exe",
                Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "gh.exe",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError(
        "GitHub CLI (gh) was not found. Install GitHub CLI or rerun the relay installer."
    )


def _publish_with_gh(body: str) -> None:
    """Publish relay JSON through gh using UTF-8 regardless of Windows console code page."""

    payload = json.dumps({"body": body}, ensure_ascii=False)
    command = [
        _find_gh(),
        "api",
        "--method",
        "PATCH",
        f"repos/{RELAY_REPO}/issues/comments/{RELAY_COMMENT_ID}",
        "--input",
        "-",
    ]
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"GitHub relay update failed: {detail}")


def require_fresh_market_data(completed_through: str, *, now=None) -> float:
    age = completed_through_age_seconds(completed_through, now=now)
    if age > RELAY_FRESH_SECONDS:
        raise RuntimeError(f"market data is stale; completed through {completed_through}, age {age / 60:.2f} minutes")
    return age


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Acquire/validate/encode without updating the GitHub comment.")
    parser.add_argument("--cache-root", type=Path, default=CACHE_ROOT)
    args = parser.parse_args(argv)
    args.cache_root.mkdir(parents=True, exist_ok=True)
    config = ModelConfig(display_timezone="UTC")
    market, metadata = build_recent_market_data(
        cache_root=args.cache_root,
        history_days=DEFAULT_HISTORY_DAYS,
        now=_utc_now(),
    )
    if "delayed hosted fallback" in metadata.source.lower():
        raise RuntimeError(
            "This machine also received Binance HTTP 451. Relay publishing stopped rather than "
            "mislabel delayed archive data as near-real-time."
        )
    require_fresh_market_data(metadata.completed_through_utc, now=_utc_now())
    derived = build_derived_features(market.frame, config)
    usable = derived.dropna(subset=["effort_score", "result_score"])
    if usable.empty:
        raise RuntimeError("No usable derived states were available after warm-up.")
    publication_time = _utc_now()
    body = build_relay_comment(
        derived,
        source="Official Binance USDⓈ-M via local near-real-time relay",
        completed_through_utc=metadata.completed_through_utc,
        oi_coverage=metadata.oi_coverage,
        future_oi_matches=metadata.future_oi_matches,
        updated_at=publication_time,
    )
    # Recheck immediately before the external write, after acquisition/model work.
    checked_at = _utc_now()
    age = require_fresh_market_data(metadata.completed_through_utc, now=checked_at)
    published_frame, relay_meta = parse_relay_comment(body, now=checked_at)
    if not relay_meta.fresh:
        raise RuntimeError("Relay payload became stale before publication.")
    if not args.dry_run:
        _publish_with_gh(body)
    current = usable.iloc[-1]
    print(json.dumps({
        "dry_run": args.dry_run, "publication_timestamp": publication_time.isoformat(),
        "completed_through_timestamp": metadata.completed_through_utc,
        "market_data_age_seconds": age, "market_data_age_minutes": age / 60,
        "latest_state_timestamp": str(published_frame.timestamp.max()),
        "rows": len(published_frame), "market_rows": metadata.rows,
        "oi_coverage": metadata.oi_coverage, "future_oi_matches": metadata.future_oi_matches,
        "cache_hits": metadata.cache_hits, "downloads": metadata.downloads,
    }))
    print(
        ("Dry-run relay (not published): " if args.dry_run else "Published relay: ")
        + f"{current['timestamp']} · Effort {current['effort_score']:+.2f} · "
        f"Result {current['result_score']:+.2f} · {current['positioning_state']}"
    )
    return 0


def run_cli(argv=None) -> int:
    try:
        return main(argv)
    except Exception as error:  # scheduled-task boundary: keep one concise error line
        print(f"Relay publish failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
