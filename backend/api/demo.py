"""Cached demo match ("Watch demo match" in Judge mode).

A bundle stores only what cannot be regenerated: the moments and overlays the pipeline produced
(including agent output). Events and tracking are regenerated deterministically from the scenario,
and the bundle's fingerprint proves both sides describe the same match.

    python -m backend.cli build-demo --scenario derby_balanced     # runs PIPELINE_PLUGINS once
    -> demo/match_001.bundle.json  (commit it)

Every demo viewer gets a private playback (own clock, pause, speed, seek) with zero model calls
and no Event Hubs traffic, so judges can never exhaust quota or credit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shared.schemas import SCHEMA_VERSION, SyntheticEvent

from backend.services.consumer import MatchStateConsumer
from backend.services.stream import LocalBus
from backend.simulator.replay import ReplayController

from . import feed
from .hub import message
from .library import LoadedMatch
from .plugins import PipelineContext

log = logging.getLogger("everyfan.demo")


def fingerprint(events: list[SyntheticEvent]) -> str:
    """Stable identity of a match: robust to float formatting, sensitive to any change in the story."""
    h = hashlib.sha256()
    for e in events:
        h.update(f"{e.event_id}|{e.type}|{e.team_id}|{e.player_id}|{e.game_clock_s}|{e.outcome}\n".encode())
    return h.hexdigest()


@dataclass
class DemoBundle:
    match_id: str
    scenario_id: str
    fingerprint: str
    plugins: list[str]
    items: list[dict] = field(default_factory=list)  # {"type", "game_time_s", "data"} sorted by time
    created_at: str = ""
    stale: bool = False
    # Recap agent output recorded at build time, keyed "persona|language|club_id" (zero cost to serve).
    recaps: dict[str, dict] = field(default_factory=dict)
    advanced: dict = field(default_factory=dict)  # optional report/coach/Q&A recordings, outside frozen contracts

    @property
    def times(self) -> list[float]:
        return [i["game_time_s"] for i in self.items]

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for i in self.items:
            out[i["type"]] = out.get(i["type"], 0) + 1
        return out

    def overlays(self) -> list[dict]:
        return [i["data"] for i in self.items if i["type"] == "overlay"]

    def overlay_sources(self) -> dict:
        out: dict[str, int] = {}
        for o in self.overlays():
            key = f'{o.get("source")}/{o.get("verification_status")}'
            out[key] = out.get(key, 0) + 1
        return out

    def overlays_for(self, moment_id: str, persona: str | None = None, language: str | None = None) -> list[dict]:
        """Cached overlays for a moment (live-mode fallback when the token cap is reached)."""
        return [i["data"] for i in self.items if i["type"] == "overlay" and i["data"]["moment_id"] == moment_id
                and (persona is None or i["data"]["persona"] == persona)
                and (language is None or i["data"]["language"] == language)]

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.match_id}.bundle.json"
        body = {"schema_version": SCHEMA_VERSION, "match_id": self.match_id, "scenario_id": self.scenario_id,
                "fingerprint": self.fingerprint, "plugins": self.plugins, "created_at": self.created_at,
                "counts": self.counts(), "items": self.items}
        if self.recaps:
            body["recaps"] = self.recaps
        encoded = json.dumps(body, ensure_ascii=False, indent=1)
        if self.advanced:
            # Recorded facts repeat across personas; compact this optional payload while
            # retaining the existing overlay representation for readable diffs.
            encoded = encoded[:-2] + ',\n "advanced": ' + json.dumps(self.advanced, ensure_ascii=False, separators=(",", ":")) + "\n}"
        path.write_text(encoded, encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "DemoBundle":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        items = sorted(d["items"], key=lambda i: (i["game_time_s"], i["type"] != "moment"))
        return cls(d["match_id"], d["scenario_id"], d["fingerprint"], d.get("plugins", []), items,
                   d.get("created_at", ""), recaps=d.get("recaps", {}), advanced=d.get("advanced", {}))


class DemoStore:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.bundles: dict[str, DemoBundle] = {}
        for path in sorted(self.folder.glob("*.bundle.json")):
            try:
                b = DemoBundle.load(path)
                self.bundles[b.match_id] = b
            except Exception:
                log.exception("bad demo bundle %s", path)

    def get(self, match: LoadedMatch) -> DemoBundle:
        """The bundle for this match, or an empty one if missing or stale (demo still plays)."""
        fp = fingerprint(match.events)
        b = self.bundles.get(match.metadata.match_id)
        if b is None:
            return DemoBundle(match.metadata.match_id, match.spec.scenario_id, fp, [], [])
        if b.fingerprint != fp:
            if not b.stale:
                log.warning("demo bundle for %s does not match the current simulation; ignoring its items",
                            match.metadata.match_id)
            b.stale = True
            return DemoBundle(match.metadata.match_id, match.spec.scenario_id, fp, [], [], stale=True)
        return b

    def catalog(self) -> list[dict]:
        return [{"match_id": b.match_id, "scenario_id": b.scenario_id, "plugins": b.plugins,
                 "created_at": b.created_at, "counts": b.counts(), "stale": b.stale,
                 "overlay_sources": b.overlay_sources(), "recaps": len(b.recaps)}
                for b in self.bundles.values()]


async def build_bundle(match: LoadedMatch, ctx: PipelineContext) -> DemoBundle:
    """Run the whole pipeline once, as fast as possible, and record moments and overlays."""
    ctx.recording = []
    bus = LocalBus()
    sub = bus.subscribe()

    async def on_reset(state):
        ctx.run_ids[state.match_id] = state.run_id
        await ctx.dispatch(ctx.reset_handlers, state)

    consumer = MatchStateConsumer(
        on_reset=on_reset,
        on_event=lambda e, s: ctx.dispatch(ctx.event_handlers, e, s),
        on_tracking=lambda f, s: ctx.dispatch(ctx.tracking_handlers, f, s),
        on_control=lambda c, s: ctx.dispatch(ctx.control_handlers, c, s),
    )
    task = asyncio.create_task(consumer.consume(sub, stop_when_finished=True))
    ctrl = ReplayController(match.metadata, match.events, match.frames, bus.publisher(), speed=0)
    await ctrl.run()
    await task
    await ctx.drain()
    items = sorted(ctx.recording, key=lambda i: (i["game_time_s"], i["type"] != "moment"))
    ctx.recording = None
    return DemoBundle(match.metadata.match_id, match.spec.scenario_id, fingerprint(match.events),
                      list(ctx.loaded_plugins), items, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class DemoPlayer:
    """One viewer's private playback of a cached match."""

    def __init__(self, match: LoadedMatch, bundle: DemoBundle, send: Callable[[dict], None], speed: float = 20.0,
                 start_at_s: float = 0.0, include_tracking: bool = True) -> None:
        self.match, self.bundle, self.send = match, bundle, send
        self.bus = LocalBus()
        self.ctrl = ReplayController(match.metadata, match.events, match.frames, self.bus.publisher(),
                                     speed=speed, include_tracking=include_tracking, start_at_s=start_at_s)
        self.times = bundle.times
        self.next_item = 0
        self.target_s = start_at_s
        self.consumer = MatchStateConsumer(on_reset=self._on_reset, on_event=self._on_event,
                                           on_tracking=self._on_tracking, on_control=self._on_control)

    # consumer callbacks -> viewer messages
    def _on_reset(self, state) -> None:
        self.next_item = 0
        self.send(feed.reset_msg(state))
        self.send(feed.metadata_msg(state))

    def _release(self, state) -> None:
        now = state.game_time_s
        while self.next_item < len(self.bundle.items) and self.times[self.next_item] <= now:
            item = self.bundle.items[self.next_item]
            self.next_item += 1
            if item["type"] == "overlay" and item["game_time_s"] + item["data"].get("ttl_s", 8) < self.target_s:
                continue  # already expired before the point the viewer jumped to
            self.send(message(item["type"], state.match_id, state.run_id, item["game_time_s"], item["data"]))

    def _on_event(self, e, state) -> None:
        if e.game_time_s >= self.target_s - 0.01:
            self.send(feed.event_msg(e, state))
        self._release(state)
        if e.game_time_s >= self.target_s - 0.01 or e.seq % 200 == 0:
            self.send(feed.state_msg(state))

    def _on_tracking(self, f, state) -> None:
        self.send(feed.tracking_msg(f, state))
        self._release(state)

    def _on_control(self, c, state) -> None:
        self.send(feed.control_msg(c, state))
        if c.action in ("run_finished", "seeked"):
            self.send(feed.state_msg(state))

    # viewer controls
    def control(self, action: str, value: float | None = None) -> None:
        if action == "pause":
            self.ctrl.pause()
        elif action == "resume":
            self.ctrl.resume()
        elif action == "speed" and value is not None:
            self.ctrl.set_speed(min(max(float(value), 0.5), 60.0))
        elif action == "seek" and value is not None:
            self.target_s = min(max(float(value) * 60.0, 0.0), 5399.0)
            self.ctrl.seek(self.target_s)
            if self.ctrl.state == "paused":
                self.ctrl.resume()

    async def run(self) -> dict:
        sub = self.bus.subscribe()
        task = asyncio.create_task(self.consumer.consume(sub, stop_when_finished=False))
        try:
            return await self.ctrl.run()
        finally:
            await sub.close()
            await asyncio.wait_for(task, 5)

    def stop(self) -> None:
        self.ctrl.stop()
