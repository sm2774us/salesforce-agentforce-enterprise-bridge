"""Minimal in-process metrics rendered in Prometheus text format."""

from __future__ import annotations

import collections
import math


class Metrics:
    """Counters plus a bounded latency window."""

    def __init__(self, latency_window: int = 4096) -> None:
        """Initializes empty metrics."""
        self._counters: collections.Counter[str] = collections.Counter()
        self._latencies: collections.deque[float] = collections.deque(
            maxlen=latency_window
        )

    def incr(self, name: str, amount: int = 1) -> None:
        """Increments a counter."""
        self._counters[name] += amount

    def counter(self, name: str) -> int:
        """Returns a counter's value (0 if unseen)."""
        return self._counters[name]

    def observe_latency(self, seconds: float) -> None:
        """Records one latency sample in seconds."""
        self._latencies.append(seconds)

    def percentile(self, q: float) -> float:
        """Nearest-rank percentile (q in [0, 100]) in seconds."""
        if not self._latencies:
            return 0.0
        ordered = sorted(self._latencies)
        rank = max(1, math.ceil(q / 100 * len(ordered)))
        return ordered[rank - 1]

    def render(self) -> str:
        """Renders Prometheus exposition text."""
        lines = [
            f"bridge_{k}_total {v}" for k, v in sorted(self._counters.items())
        ]
        for q in (50, 95):
            lines.append(
                f'bridge_latency_seconds{{quantile="0.{q}"}} '
                f"{self.percentile(q):.6f}"
            )
        return "\n".join(lines) + "\n"
