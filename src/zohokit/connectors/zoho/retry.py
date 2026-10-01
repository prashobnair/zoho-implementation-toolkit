"""HTTP resilience: timeouts, retries with backoff + jitter (STD-H1)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0


def _default_jitter() -> float:
    """Small random spread so concurrent retries do not march in lockstep."""
    return random.uniform(0, 0.25)


def _default_sleep(seconds: float) -> None:
    """Blocking sleep (tests inject a recorder instead)."""
    time.sleep(seconds)


RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 5


def default_timeouts() -> httpx.Timeout:
    """Connect 5s, read 30s per STD-H1."""
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=CONNECT_TIMEOUT
    )


@dataclass
class RetryPolicy:
    """Retry with exponential backoff, jitter and Retry-After (STD-H1)."""

    max_attempts: int = MAX_ATTEMPTS
    base_delay: float = 0.5
    max_delay: float = 8.0
    sleep: Callable[[float], None] = field(default_factory=lambda: _default_sleep)
    jitter: Callable[[], float] = field(default_factory=lambda: _default_jitter)

    def delay_for(self, attempt: int, retry_after: str | None) -> float:
        """Delay before the next attempt (1-indexed *attempt* just failed)."""
        if retry_after is not None:
            try:
                return max(min(float(retry_after), self.max_delay), 0.0)
            except ValueError:
                pass
        delay = min(self.base_delay * (2.0 ** (attempt - 1)), self.max_delay)
        return min(delay + self.jitter(), self.max_delay)

    @staticmethod
    def is_retryable_status(status: int) -> bool:
        """Retry on 429/502/503/504 only."""
        return status in RETRYABLE_STATUS

    @staticmethod
    def is_retryable_error(exc: BaseException) -> bool:
        """Retry on connection resets and timeouts, never on guard errors."""
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
            ),
        )


__all__: list[str] = [
    "CONNECT_TIMEOUT",
    "MAX_ATTEMPTS",
    "READ_TIMEOUT",
    "RETRYABLE_STATUS",
    "RetryPolicy",
    "default_timeouts",
]
