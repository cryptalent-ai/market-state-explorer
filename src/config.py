"""Configuration values for the market-state model."""

from __future__ import annotations

from dataclasses import dataclass


EPS = 1e-12


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """User-configurable model and display parameters."""

    atr_period: int = 14
    normalization_window: int = 288
    min_reference_bars: int = 96
    positioning_threshold: float = 0.75
    boundary_threshold: float = 0.25
    trail_length: int = 50
    display_history: int = 500
    forward_horizons: tuple[int, ...] = (5, 10, 20)
    random_seed: int = 42
    display_timezone: str = "Asia/Taipei"
    low_effort_threshold: float = -0.50
    high_result_threshold: float = 0.75
    high_effort_threshold: float = 0.75
    low_result_threshold: float = -0.50

    def __post_init__(self) -> None:
        if self.atr_period < 1:
            raise ValueError("ATR period must be positive")
        if self.normalization_window < 2:
            raise ValueError("Normalization window must be at least 2")
        if not 1 <= self.min_reference_bars <= self.normalization_window:
            raise ValueError(
                "Minimum reference bars must be between 1 and the "
                "normalization window"
            )
        if not self.forward_horizons or any(
            horizon < 1 for horizon in self.forward_horizons
        ):
            raise ValueError("Forward horizons must contain positive integers")
