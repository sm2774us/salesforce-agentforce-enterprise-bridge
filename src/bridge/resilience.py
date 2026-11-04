"""Retry with full-jitter backoff and a circuit breaker."""

from __future__ import annotations

import asyncio
import enum
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    is_retryable: Callable[[Exception], bool] = lambda _: True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Runs ``operation`` with exponential backoff and full jitter.

    Args:
      operation: Zero-argument coroutine factory.
      attempts: Total attempts (>= 1).
      base_delay: Initial backoff ceiling in seconds.
      max_delay: Maximum backoff ceiling in seconds.
      is_retryable: Predicate deciding whether an exception is retried.
      sleep: Injectable sleep (tests pass a no-op).
      rng: Injectable uniform [0, 1) generator.

    Returns:
      The operation's result.

    Raises:
      ValueError: If ``attempts`` < 1.
      Exception: The last error when retries are exhausted or non-retryable.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(attempts - 1):
        try:
            return await operation()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            await sleep(rng() * min(max_delay, base_delay * 2**attempt))
    return await operation()


class CircuitState(str, enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Opens after consecutive failures; probes again after a cool-down."""

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initializes the breaker.

        Args:
          failure_threshold: Consecutive failures before opening.
          reset_timeout: Seconds to stay open before half-open probing.
          clock: Monotonic clock (injectable for tests).
        """
        self._threshold = failure_threshold
        self._reset = reset_timeout
        self._clock = clock
        self._failures = 0
        self._opened_at = 0.0
        self._state = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Current state, promoting OPEN to HALF_OPEN after the cool-down."""
        if (
            self._state is CircuitState.OPEN
            and self._clock() - self._opened_at >= self._reset
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """Returns True if a call may proceed."""
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        """Resets the breaker."""
        self._failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Counts a failure and opens the circuit when warranted."""
        self._failures += 1
        if (
            self._state is CircuitState.HALF_OPEN
            or self._failures >= self._threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
