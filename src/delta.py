"""Exchange-taker-volume Delta reconstruction and validation."""

from __future__ import annotations

import numpy as np
import pandas as pd


INVALID_DELTA_SOURCE = "INVALID_DELTA_SOURCE"


def reconstruct_delta(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive signed Delta exactly from Binance taker-buy base volume."""

    result = frame.copy()
    volume = pd.to_numeric(result["volume"], errors="coerce")
    taker_buy = pd.to_numeric(
        result["taker_buy_base_volume"], errors="coerce"
    )
    tolerance = 1e-9 * np.maximum(1.0, volume.abs())
    valid = (
        volume.notna()
        & taker_buy.notna()
        & volume.ge(-tolerance)
        & taker_buy.ge(-tolerance)
        & taker_buy.le(volume + tolerance)
    )
    result["aggressive_buy_volume"] = taker_buy
    result["aggressive_sell_volume"] = volume - taker_buy
    result["delta"] = 2.0 * taker_buy - volume
    valid &= result["aggressive_sell_volume"].ge(-tolerance)
    valid &= result["delta"].abs().le(volume + tolerance)
    result["delta_source_valid"] = valid.astype(bool)
    result["builder_data_quality_flag"] = np.where(
        valid, "", INVALID_DELTA_SOURCE
    )
    result["data_quality_flag"] = result["builder_data_quality_flag"]
    return result
