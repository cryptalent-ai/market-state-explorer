"""Processed-dataset metadata construction and serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """JSON-serializable audit metadata for a built dataset."""

    values: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.values, indent=2, sort_keys=True, default=str)


def create_metadata(
    *,
    provider_metadata: dict[str, Any],
    start: str,
    end: str,
    rows: int,
    quality: dict[str, Any],
    kline_sources: list[str],
    oi_sources: list[str],
    cache_hits: int,
    downloads: int,
    max_oi_age_seconds: int,
) -> DatasetMetadata:
    values = {
        **provider_metadata,
        "version": "0.1.2",
        "start": start,
        "end": end,
        "timezone_internal": "UTC",
        "display_timezone": "Asia/Taipei",
        "delta_method": "2 * taker_buy_base_volume - volume",
        "oi_alignment": (
            "Backward as-of: latest period-end timestamp <= canonical bar close; "
            f"maximum age {max_oi_age_seconds} seconds; no interpolation"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "dataset_quality": quality,
        "official_source_urls": {
            "klines": sorted(set(kline_sources)),
            "open_interest": sorted(set(oi_sources)),
        },
        "cache_hits": cache_hits,
        "downloads": downloads,
    }
    return DatasetMetadata(values)


def unique_output_path(directory: Path, filename: str) -> Path:
    """Avoid overwriting an earlier processed dataset or metadata artifact."""

    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return candidate.with_name(f"{candidate.stem}-{stamp}{candidate.suffix}")
