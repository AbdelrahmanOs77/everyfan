"""Fan-out of viewer messages to WebSocket clients, with the broadcast delay.

Viewer message (JSON, one per WebSocket frame):
    {"type": "...", "match_id": "match_001", "run_id": "...", "game_time_s": 763.5, "data": {...}}

types: hello, reset, metadata, state, event, tracking, control, replay, moment, overlay, error

Broadcast delay: the live picture (reset/metadata/state/event/tracking/control) reaches viewers
BROADCAST_DELAY_S real seconds after ingest, like a TV delay. Moments and overlays skip the delay,
so an agent that finishes inside the delay budget lands on screen exactly at its `show_at_s`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field

DELAYED = {"reset", "metadata", "state", "event", "tracking", "control"}


def message(kind: str, match_id: str, run_id: str | None, game_time_s: float, data) -> dict:
    return {"type": kind, "match_id": match_id, "run_id": run_id, "game_time_s": round(float(game_time_s), 2),
            "data": data}


@dataclass(eq=False)
class ViewerClient:
    key: str
    persona: str | None = None
    language: str | None = None
    tracking_hz: float = 2.0
    club: str | None = None  # Favorite Club viewers only receive their club's club-persona overlays
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=4000))
    dropped: int = 0
    lagging: bool = False

    def wants(self, msg: dict) -> bool:
        kind = msg["type"]
        if kind == "tracking":
            if self.tracking_hz <= 0:
                return False
            if self.tracking_hz < 2:
                step = max(1, round(2 / self.tracking_hz))
                return msg["data"].get("frame", 0) % step == 0
        if kind == "overlay":
            d = msg["data"]
            if self.persona and d.get("persona") != self.persona:
                return False
            if self.language and d.get("language") != self.language:
                return False
            if self.club and d.get("persona") == "club" and d.get("fields", {}).get("club_id") != self.club:
                return False
        return True

    def offer(self, text: str, msg: dict) -> None:
        if self.lagging or not self.wants(msg):
            return
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            if msg["type"] == "tracking":
                self.dropped += 1
            else:
                self.lagging = True  # too slow for important messages: the socket will be closed


class Channel:
    """One match: its viewers, its delay line and the snapshot a late joiner needs."""

    def __init__(self, match_id: str, delay_s: float) -> None:
        self.match_id = match_id
        self.delay_s = delay_s
        self.clients: set[ViewerClient] = set()
        self.last_viewer_seen = time.monotonic()
        self.snapshot: dict = {"metadata": None, "state": None, "replay": None,
                               "moments": deque(maxlen=200), "overlays": deque(maxlen=100)}
        self._line: deque[tuple[float, dict, str]] = deque()
        self._wake = asyncio.Event()
        self._pump: asyncio.Task | None = None

    def add(self, client: ViewerClient) -> None:
        self.clients.add(client)
        self.last_viewer_seen = time.monotonic()

    def remove(self, client: ViewerClient) -> None:
        self.clients.discard(client)
        self.last_viewer_seen = time.monotonic()

    def idle_for(self) -> float:
        return 0.0 if self.clients else time.monotonic() - self.last_viewer_seen

    def snapshot_messages(self) -> list[dict]:
        out = [m for m in (self.snapshot["metadata"], self.snapshot["state"], self.snapshot["replay"]) if m]
        return out + list(self.snapshot["moments"]) + list(self.snapshot["overlays"])

    def _remember(self, msg: dict) -> None:
        kind = msg["type"]
        if kind == "reset":
            self.snapshot["moments"].clear()
            self.snapshot["overlays"].clear()
        elif kind in ("metadata", "state", "replay"):
            self.snapshot[kind] = msg
        elif kind == "moment":
            self.snapshot["moments"].append(msg)
        elif kind == "overlay":
            self.snapshot["overlays"].append(msg)

    def _deliver(self, msg: dict, text: str) -> None:
        self._remember(msg)
        for c in list(self.clients):
            c.offer(text, msg)

    def publish(self, msg: dict) -> None:
        text = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
        if msg["type"] in DELAYED and self.delay_s > 0:
            self._line.append((time.monotonic() + self.delay_s, msg, text))
            self._wake.set()
            if self._pump is None or self._pump.done():
                self._pump = asyncio.get_running_loop().create_task(self._run_pump())
        else:
            self._deliver(msg, text)

    async def _run_pump(self) -> None:
        while True:
            if not self._line:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=60)
                except asyncio.TimeoutError:
                    return
                continue
            due, msg, text = self._line[0]
            wait = due - time.monotonic()
            if wait > 0:
                await asyncio.sleep(min(wait, 0.05))
                continue
            self._line.popleft()
            self._deliver(msg, text)


class ViewerHub:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.channels: dict[str, Channel] = {}

    def channel(self, match_id: str) -> Channel:
        if match_id not in self.channels:
            self.channels[match_id] = Channel(match_id, self.delay_s)
        return self.channels[match_id]

    def viewer_count(self) -> int:
        return sum(len(c.clients) for c in self.channels.values())
