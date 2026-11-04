"""Bounded async event bus with dedupe, DLQ and schema-drift capture.

Mirrors Kafka semantics (at-least-once, consumer groups) in-process; the
``EventBus`` surface is the seam where a Kafka consumer plugs in.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from bridge.models import TelemetryEvent

_LOG = logging.getLogger(__name__)
Handler = Callable[[TelemetryEvent], Awaitable[Any]]


class BusFullError(RuntimeError):
    """The queue is at capacity (apply backpressure upstream)."""


class SchemaDriftError(ValueError):
    """The payload violates the TelemetryEvent contract."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        """Carries pydantic's structured errors."""
        super().__init__("schema drift")
        self.errors = errors


class EventBus:
    """Worker-pool event bus."""

    def __init__(
        self,
        handler: Handler,
        capacity: int = 1000,
        workers: int = 4,
        dlq_size: int = 1000,
        dedupe_size: int = 10_000,
    ) -> None:
        """Initializes the bus (call ``start`` to launch workers)."""
        self._handler = handler
        self._queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue(capacity)
        self._workers_n = workers
        self._tasks: list[asyncio.Task[None]] = []
        self._seen: collections.OrderedDict[str, None] = (
            collections.OrderedDict()
        )
        self._dedupe_size = dedupe_size
        self.dlq: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=dlq_size
        )

    @property
    def running(self) -> bool:
        """True while workers are active."""
        return bool(self._tasks)

    def publish_raw(
        self, payload: dict[str, Any]
    ) -> tuple[TelemetryEvent, bool]:
        """Validates and enqueues a payload.

        Returns:
          (event, is_new); is_new is False for a duplicate event_id.

        Raises:
          SchemaDriftError: Payload invalid (also recorded in the DLQ).
          BusFullError: Queue at capacity.
        """
        try:
            event = TelemetryEvent.model_validate(payload)
        except ValidationError as exc:
            errors = exc.errors(
                include_url=False, include_context=False, include_input=False
            )
            self.dlq.append({"reason": "schema_drift", "errors": errors})
            raise SchemaDriftError(errors) from exc
        if event.event_id in self._seen:
            return event, False
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            raise BusFullError("event queue full") from exc
        self._seen[event.event_id] = None
        while len(self._seen) > self._dedupe_size:
            self._seen.popitem(last=False)
        return event, True

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._handler(event)
            except Exception as exc:
                _LOG.exception("handler failed for %s", event.event_id)
                self.dlq.append(
                    {
                        "reason": "handler_error",
                        "event_id": event.event_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            finally:
                self._queue.task_done()

    async def start(self) -> None:
        """Launches the worker pool (idempotent)."""
        if not self._tasks:
            self._tasks = [
                asyncio.create_task(self._worker())
                for _ in range(self._workers_n)
            ]

    async def drain(self) -> None:
        """Waits until every queued event has been handled."""
        await self._queue.join()

    async def stop(self) -> None:
        """Drains, then cancels workers."""
        await self.drain()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
