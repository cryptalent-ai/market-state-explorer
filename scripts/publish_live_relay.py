"""Publish a near-real-time derived market-state snapshot from a local machine.

This script is intended to run on a machine where Binance USDⓈ-M public REST is
legally accessible. It does not use a proxy, VPN, or geo-bypass. The published
GitHub issue comment contains only derived/public market data and no secrets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from src.config import ModelConfig
from src.features import build_derived_features
from src.live_data import DEFAULT_HISTORY_DAYS, build_recent_market_data
from src.relay import RELAY_COMMENT_ID, RELAY_REPO, build_relay_comment

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
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"GitHub relay update failed: {detail}")


def main() -> int:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    config = ModelConfig(display_timezone="UTC")
    market, metadata = build_recent_market_data(
        cache_root=CACHE_ROOT,
        history_days=DEFAULT_HISTORY_DAYS,
    )
    if "delayed hosted fallback" in metadata.source.lower():
        raise RuntimeError(
            "This machine also received Binance HTTP 451. Relay publishing stopped rather than "
            "mislabel delayed archive data as near-real-time."
        )
    derived = build_derived_features(market.frame, config)
    usable = derived.dropna(subset=["effort_score", "result_score"])
    if usable.empty:
        raise RuntimeError("No usable derived states were available after warm-up.")
    body = build_relay_comment(
        derived,
        source="Official Binance USDⓈ-M via local near-real-time relay",
        completed_through_utc=metadata.completed_through_utc,
        oi_coverage=metadata.oi_coverage,
        future_oi_matches=metadata.future_oi_matches,
    )
    _publish_with_gh(body)
    current = usable.iloc[-1]
    print(
        "Published relay: "
        f"{current['timestamp']} · Effort {current['effort_score']:+.2f} · "
        f"Result {current['result_score']:+.2f} · {current['positioning_state']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # scheduled-task boundary: keep one concise error line
        print(f"Relay publish failed: {error}", file=sys.stderr)
        raise SystemExit(1)
