"""Provider contracts and user-meaningful source errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


ProgressCallback = Callable[[str], None]


class ProviderError(RuntimeError):
    """Base class for official-source failures."""


class NetworkFailure(ProviderError):
    """The official source could not be reached after bounded retries."""


class RateLimitError(ProviderError):
    """The official source rate-limited the request."""


class SourceUnavailable(ProviderError):
    """An official source object or endpoint was unavailable."""


class InvalidSourceResponse(ProviderError):
    """The official source returned malformed or semantically invalid data."""


@dataclass(slots=True)
class SourceBatch:
    """Provider data plus an audit record of acquisition behavior."""

    data: pd.DataFrame
    source_urls: list[str] = field(default_factory=list)
    cache_hits: int = 0
    downloads: int = 0
    missing_dates: list[date] = field(default_factory=list)


class MarketDataProvider(ABC):
    """Isolation boundary between model code and public market-data sources."""

    @abstractmethod
    def fetch_klines(
        self,
        start: date,
        end: date,
        progress: ProgressCallback | None = None,
    ) -> SourceBatch:
        """Fetch inclusive UTC calendar dates of kline source data."""

    @abstractmethod
    def fetch_open_interest(
        self,
        start: date,
        end: date,
        progress: ProgressCallback | None = None,
    ) -> SourceBatch:
        """Fetch inclusive UTC calendar dates of OI source data."""

    @abstractmethod
    def source_metadata(self) -> dict[str, Any]:
        """Describe official fields, units, timestamps, and source identifiers."""
