"""Paced replay of a generated match onto a Publisher.

    controller = ReplayController(match_folder_or_generated, publisher, speed=20)
    task = asyncio.create_task(controller.run())
    controller.pause(); controller.resume(); controller.set_speed(5); controller.seek(3600)

* speed 1 = real time, 5, 20 ... ; speed 0 = as fast as possible (tests, cache warm-up).
* Every run (and every backwards seek) gets a fresh run_id and starts with the match
  metadata, so consumers can reset their state cleanly.
* Starting or seeking to minute M first sends all events before M in one burst
  (no tracking), so downstream state is correct, then continues paced.
"""

from __future__ import annotations

import asyncio
import bisect
import time
import uuid
from dataclasses import dataclass

from shared.schemas import (
    ControlEnvelope,
    ControlMessage,
    EventEnvelope,
    MatchMetadata,
    MetadataEnvelope,
    SyntheticEvent,
    TrackingEnvelope,
    TrackingFrame,
)

from backend.services.stream import Publisher

TICK_S = 0.05


@dataclass(frozen=True)
class _Item:
    t: float
    order: int  # events before tracking at the same instant
    kind: str
    obj: SyntheticEvent | TrackingFrame


def _new_run_id() -> str:
    return f"run_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


class ReplayController:
    def __init__(self, metadata: MatchMetadata, events: list[SyntheticEvent], frames: list[TrackingFrame],
                 publisher: Publisher, speed: float = 1.0, include_tracking: bool = True,
                 start_at_s: float = 0.0) -> None:
        self.meta = metadata
        self.publisher = publisher
        self.speed = float(speed)
        items = [_Item(e.game_time_s, 0, "event", e) for e in events]
        if include_tracking:
            items += [_Item(f.game_clock_s, 1, "tracking", f) for f in frames]
        items.sort(key=lambda i: (i.t, i.order, getattr(i.obj, "seq", 0)))
        self.items = items
        self._times = [i.t for i in items]
        self.idx = 0
        self.run_id = _new_run_id()
        self.state = "idle"  # idle | running | paused | finished | stopped
        self._game_anchor = float(start_at_s)
        self._wall_anchor = 0.0
        self._resume = asyncio.Event()
        self._resume.set()
        self._pending_seek: float | None = start_at_s if start_at_s > 0 else None
        self.sent = 0

    # ----------------------------------------------------------- controls

    def game_time(self) -> float:
        if self.state != "running" or self.speed == 0:
            return self._game_anchor
        return self._game_anchor + (time.monotonic() - self._wall_anchor) * self.speed

    def _reanchor(self) -> None:
        self._game_anchor = self.game_time()
        self._wall_anchor = time.monotonic()

    def pause(self) -> None:
        if self.state == "running":
            self._reanchor()
            self.state = "paused"
            self._resume.clear()

    def resume(self) -> None:
        if self.state == "paused":
            self._wall_anchor = time.monotonic()
            self.state = "running"
            self._resume.set()

    def set_speed(self, speed: float) -> None:
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self._reanchor()
        self.speed = float(speed)

    def seek(self, t: float) -> None:
        self._pending_seek = max(0.0, float(t))

    def stop(self) -> None:
        self.state = "stopped"
        self._resume.set()

    def status(self) -> dict:
        return {
            "match_id": self.meta.match_id,
            "run_id": self.run_id,
            "state": self.state,
            "speed": self.speed,
            "game_time_s": round(self.game_time(), 2),
            "sent": self.sent,
            "progress": round(self.idx / max(len(self.items), 1), 4),
        }

    # ------------------------------------------------------------ envelopes

    def _env(self, item: _Item):
        cls = EventEnvelope if item.kind == "event" else TrackingEnvelope
        return cls(match_id=self.meta.match_id, run_id=self.run_id, game_time_s=item.t, payload=item.obj)

    def _control(self, action: str, detail: str | None = None) -> ControlEnvelope:
        return ControlEnvelope(match_id=self.meta.match_id, run_id=self.run_id, game_time_s=round(self._game_anchor, 2),
                               payload=ControlMessage(action=action, speed=self.speed, detail=detail))

    async def _send(self, envs: list) -> None:
        if envs:
            await self.publisher.send(envs)
            self.sent += len(envs)

    async def _start_run(self, at: float, new_id: bool = True) -> None:
        """(New) run_id, metadata, then a burst of every event before `at`."""
        if new_id:
            self.run_id = _new_run_id()
        self._game_anchor = at
        await self._send([MetadataEnvelope(match_id=self.meta.match_id, run_id=self.run_id, game_time_s=0.0,
                                           payload=self.meta), self._control("run_started")])
        end = bisect.bisect_left(self._times, at)
        burst = [self._env(i) for i in self.items[:end] if i.kind == "event"]
        for k in range(0, len(burst), 200):
            await self._send(burst[k:k + 200])
        self.idx = end
        if at > 0:
            await self._send([self._control("seeked", f"caught up to {at:.0f}s")])

    # ------------------------------------------------------------------ run

    async def run(self) -> dict:
        self.state = "running"
        await self._start_run(self._pending_seek or 0.0, new_id=False)
        self._pending_seek = None
        self._wall_anchor = time.monotonic()
        while self.idx < len(self.items):
            if self.state == "stopped":
                break
            if self.state == "paused":
                await self._send([self._control("paused")])
                await self._resume.wait()
                if self.state == "stopped":
                    break
                await self._send([self._control("resumed")])
                self._wall_anchor = time.monotonic()
                continue
            if self._pending_seek is not None:
                target, self._pending_seek = self._pending_seek, None
                await self._start_run(target)
                self._wall_anchor = time.monotonic()
                continue

            now = self.game_time() if self.speed > 0 else float("inf")
            end = bisect.bisect_right(self._times, now, lo=self.idx)
            if self.speed == 0:
                end = min(self.idx + 500, len(self.items))
            if end > self.idx:
                await self._send([self._env(i) for i in self.items[self.idx:end]])
                self.idx = end
                if self.speed == 0:
                    await asyncio.sleep(0)
                continue
            wait = (self._times[self.idx] - now) / self.speed
            await asyncio.sleep(min(max(wait, 0.001), TICK_S))

        if self.state != "stopped":
            self.state = "finished"
            self._game_anchor = self._times[-1] if self._times else 0.0
            await self._send([self._control("run_finished")])
        return self.status()
