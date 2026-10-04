"""Consistent numerical and timestamp formatting."""

from __future__ import annotations

import math

import pandas as pd


def number(value: object, decimals: int = 2, signed: bool = False) -> str:
    """Format a number with a leading zero and an explicit missing marker."""

    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "NA"
    if math.isnan(numeric):
        return "NA"
    specification = f"{'+' if signed else ''}.{decimals}f"
    return format(numeric, specification)


def percent(value: object, decimals: int = 2, signed: bool = False) -> str:
    """Format a decimal fraction as a percentage."""

    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "NA"
    if math.isnan(numeric):
        return "NA"
    specification = f"{'+' if signed else ''}.{decimals}f"
    return f"{format(100.0 * numeric, specification)}%"


def timestamp(value: object, timezone: str = "Asia/Taipei") -> str:
    """Format a timestamp in the configured display timezone."""

    if pd.isna(value):
        return "NA"
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
