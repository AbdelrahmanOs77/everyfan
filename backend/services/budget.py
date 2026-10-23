"""Daily model-token cap shared by every agent call.

Owner C's agents ask before every model call and report actual usage afterwards:

    if not await ctx.budget.try_reserve(estimate):      # over today's cap
        return fallback_overlay(...)                     # deterministic template, zero cost
    result = await agent.run(...)
    await ctx.budget.settle(estimate, actual_tokens)

The counter resets at 00:00 UTC. It is persisted to a small JSON file (best effort) so a
container restart on the same replica does not reset it.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class DailyTokenBudget:
    def __init__(self, daily_cap: int, state_file: str | Path | None = None) -> None:
        self.daily_cap = int(daily_cap)
        self.state_file = Path(state_file) if state_file else None
        self._lock = asyncio.Lock()
        self.day = _today()
        self.used = 0
        self.reserved = 0
        self.denied = 0
        self._load()

    # ----------------------------------------------------------- persistence

    def _load(self) -> None:
        if not self.state_file or not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text())
            if data.get("day") == self.day:
                self.used, self.denied = int(data.get("used", 0)), int(data.get("denied", 0))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"day": self.day, "used": self.used, "denied": self.denied,
                                                   "saved_at": time.time()}))
        except OSError:
            pass

    def _roll(self) -> None:
        today = _today()
        if today != self.day:
            self.day, self.used, self.reserved, self.denied = today, 0, 0, 0

    # ----------------------------------------------------------------- API

    @property
    def enabled(self) -> bool:
        return self.daily_cap > 0

    def remaining(self) -> int:
        self._roll()
        if not self.enabled:
            return 0
        return max(0, self.daily_cap - self.used - self.reserved)

    async def try_reserve(self, tokens: int) -> bool:
        """Reserve tokens for one call. False = over the cap, use the fallback."""
        async with self._lock:
            self._roll()
            if not self.enabled or self.used + self.reserved + tokens > self.daily_cap:
                self.denied += 1
                self._save()
                return False
            self.reserved += tokens
            return True

    async def settle(self, reserved: int, actual: int) -> None:
        """Replace a reservation with the real usage reported by the model."""
        async with self._lock:
            self._roll()
            self.reserved = max(0, self.reserved - reserved)
            self.used += max(0, int(actual))
            self._save()

    def status(self) -> dict:
        self._roll()
        return {"day_utc": self.day, "daily_cap": self.daily_cap, "used": self.used,
                "reserved": self.reserved, "remaining": self.remaining(), "denied_calls": self.denied,
                "live_ai_enabled": self.enabled and self.remaining() > 0}
