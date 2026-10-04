"""Positioning significance and canonical state classification."""

from __future__ import annotations

import numpy as np
import pandas as pd


POSITIONING_LABELS: dict[tuple[int, int, int], str] = {
    (1, 1, 1): "New Long Initiative",
    (1, 1, -1): "Short Covering",
    (1, -1, 1): "Aggressive Shorts Absorbed",
    (1, -1, -1): "Bullish Price-Flow Divergence / OI Contraction",
    (-1, -1, 1): "New Short Initiative",
    (-1, -1, -1): "Long Liquidation / Closing",
    (-1, 1, 1): "Aggressive Buyers Absorbed",
    (-1, 1, -1): "Bearish Price-Flow Divergence / OI Contraction",
}
POSITIONING_STATES = tuple(POSITIONING_LABELS.values()) + (
    "Mixed / Low Conviction",
)


def significance_state(score: pd.Series, threshold: float) -> pd.Series:
    """Map a signed significance score to -1, 0, or +1."""

    values = np.select(
        [score.ge(threshold), score.le(-threshold)],
        [1, -1],
        default=0,
    )
    result = pd.Series(values, index=score.index, dtype="int8")
    return result.mask(score.isna()).astype("Int8")


def classify_positioning(
    price_state: pd.Series,
    delta_state: pd.Series,
    oi_state: pd.Series,
) -> pd.Series:
    """Classify only fully significant triplets; all others remain mixed."""

    labels: list[str] = []
    for price, delta, oi in zip(price_state, delta_state, oi_state):
        if pd.isna(price) or pd.isna(delta) or pd.isna(oi):
            labels.append("Mixed / Low Conviction")
            continue
        key = (int(price), int(delta), int(oi))
        labels.append(POSITIONING_LABELS.get(key, "Mixed / Low Conviction"))
    return pd.Series(labels, index=price_state.index, dtype="string")
