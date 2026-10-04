"""Bounded, retrying HTTP access for official public market data."""

from __future__ import annotations

from collections.abc import Callable
import json
import time
from typing import Any, Protocol

import requests

from .providers.base import (
    InvalidSourceResponse,
    NetworkFailure,
    RateLimitError,
    SourceUnavailable,
)


class ResponseLike(Protocol):
    status_code: int
    content: bytes
    headers: dict[str, str]


class SessionLike(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None,
        timeout: float,
        headers: dict[str, str],
    ) -> ResponseLike: ...


class ReliableHttpClient:
    """HTTP GET client with timeouts, exponential backoff, and finite retries."""

    def __init__(
        self,
        *,
        session: SessionLike | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 1:
            raise ValueError("Maximum retries must be at least one")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep

    def get_bytes(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> bytes:
        last_network_error: Exception | None = None
        last_rate_limit: int | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "Market-State-Explorer/0.1.2"},
                )
            except requests.RequestException as error:
                last_network_error = error
                if attempt + 1 < self.max_retries:
                    self.sleep(self.backoff_seconds * (2**attempt))
                continue

            status = int(response.status_code)
            if status == 200:
                return bytes(response.content)
            if status == 404:
                raise SourceUnavailable(f"Official source object not found: {url}")
            if status in (418, 429):
                last_rate_limit = status
                if attempt + 1 < self.max_retries:
                    retry_after = float(response.headers.get("Retry-After", 0) or 0)
                    self.sleep(max(retry_after, self.backoff_seconds * (2**attempt)))
                continue
            if 500 <= status < 600:
                if attempt + 1 < self.max_retries:
                    self.sleep(self.backoff_seconds * (2**attempt))
                    continue
                raise SourceUnavailable(
                    f"Official source returned HTTP {status}: {url}"
                )
            raise InvalidSourceResponse(
                f"Official source returned HTTP {status}: {url}"
            )

        if last_rate_limit is not None:
            raise RateLimitError(
                f"Official source rate limit persisted (HTTP {last_rate_limit})."
            )
        raise NetworkFailure(
            f"Official source could not be reached after {self.max_retries} attempts."
        ) from last_network_error

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> Any:
        payload = self.get_bytes(url, params=params)
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidSourceResponse(
                f"Official source returned invalid JSON: {url}"
            ) from error
