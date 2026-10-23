"""In-memory token-bucket rate limiter keyed by client (single replica by design)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, per_minute: float, burst: int | None = None) -> None:
        self.rate = per_minute / 60.0
        self.capacity = float(burst if burst is not None else max(1, int(per_minute)))
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Returns (allowed, seconds until the next token)."""
        now = time.monotonic()
        b = self._buckets.get(key)
        if b is None:
            b = self._buckets[key] = _Bucket(self.capacity, now)
        b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.rate)
        b.updated = now
        if b.tokens >= cost:
            b.tokens -= cost
            return True, 0.0
        if len(self._buckets) > 10_000:  # bound memory under abuse
            self._buckets.clear()
        return False, (cost - b.tokens) / self.rate if self.rate else float("inf")
