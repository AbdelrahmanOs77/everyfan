"""Owner B pipeline plugin: live stats and moments, plus Cosmos DB persistence.

    PIPELINE_PLUGINS=backend.api.template_plugin:register,backend.analytics.plugin:register

* every event -> MomentDetector -> ctx.publish_moment (Contract B) for viewers, agents and the demo bundle;
* every tracking frame -> sprint / distance badges (player_milestone moments);
* seeks: Owner A's replay first sends every earlier event in one burst (no tracking). The detector
  processes that burst so its state and moment IDs are exactly as in a full run, but those
  historic moments are not re-published; tracking before the seek point is back-filled from the
  match files so distance badges stay correct;
* with COSMOS_ENDPOINT set, events and moments are upserted to Cosmos DB in the background.

For Owner C (agents), in the same process:
    ctx.analytics.detector(match_id)            # live MomentDetector: .a (MatchAnalytics), .tracker
    ctx.analytics.snapshot(match_id)            # live stats right now (same numbers as the evidence API)
    ctx.analytics.subscribe(callback)           # callback(moment, state) after each published moment
"""

from __future__ import annotations

import asyncio
import inspect
import logging

from shared.schemas import Moment

from .config import load_config
from .moments import MomentDetector
from .store import get_store

log = logging.getLogger("everyfan.analytics")


class AnalyticsPlugin:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.cfg = load_config()
        self.store = get_store()
        self.detectors: dict[str, MomentDetector] = {}
        self.catching_up: dict[str, bool] = {}
        self.needs_backfill: dict[str, bool] = {}
        self.listeners: list = []
        self.published = 0

    # ----------------------------------------------------------- for Owner C

    def detector(self, match_id: str) -> MomentDetector | None:
        return self.detectors.get(match_id)

    def snapshot(self, match_id: str) -> dict | None:
        det = self.detectors.get(match_id)
        return det.a.snapshot() if det else None

    def subscribe(self, callback) -> None:
        self.listeners.append(callback)

    def status(self) -> dict:
        return {"matches": sorted(self.detectors), "moments_published": self.published,
                "cosmos": self.store.status() if self.store else {"enabled": False}}

    # -------------------------------------------------------------- handlers

    def reset(self, state) -> None:
        self.detectors[state.match_id] = MomentDetector(state.metadata, self.cfg)
        self.catching_up[state.match_id] = True  # until "seeked" or the first tracking frame of this run
        self.needs_backfill[state.match_id] = False

    def on_control(self, c, state) -> None:
        if c.action == "seeked":  # Owner A's replay finished sending the events before the seek point
            self.catching_up[state.match_id] = False
            self.needs_backfill[state.match_id] = True

    async def on_event(self, e, state) -> None:
        det = self.detectors.get(e.match_id)
        if det is None:
            return
        moments = det.update(e)
        if self.store:
            self.store.add_event(e, state.run_id)
        if self.catching_up.get(e.match_id):
            return  # seek burst: computed (IDs stay stable) but not re-published
        for m in moments:
            await self._publish(m, state)

    async def on_tracking(self, f, state) -> None:
        det = self.detectors.get(f.match_id)
        if det is None:
            return
        if self.catching_up.get(f.match_id) or self.needs_backfill.get(f.match_id):
            self.catching_up[f.match_id] = self.needs_backfill[f.match_id] = False
            if f.frame > 0 and det.tracker.last_frame is None:
                await self._backfill(det, f.match_id, f.frame)
        for m in det.update_tracking(f):
            await self._publish(m, state)

    async def _backfill(self, det: MomentDetector, match_id: str, before_frame: int) -> None:
        """After a seek: run the tracker over the frames we skipped, without publishing."""
        library = getattr(self.ctx, "library", None)
        if library is None:
            return
        try:
            match = await library.get(match_id)
        except Exception:
            log.exception("tracking back-fill: could not load %s", match_id)
            return

        def run() -> None:
            for frame in match.frames:
                if frame.frame >= before_frame:
                    break
                det.update_tracking(frame)

        await asyncio.to_thread(run)

    async def _publish(self, m: Moment, state) -> None:
        await self.ctx.publish_moment(m)
        self.published += 1
        if self.store:
            self.store.add_moment(m, state.run_id)
        for cb in self.listeners:
            try:
                result = cb(m, state)
                if inspect.isawaitable(result):
                    self.ctx.spawn(result)
            except Exception:
                log.exception("analytics listener failed")


def register(ctx) -> None:
    plugin = AnalyticsPlugin(ctx)
    ctx.analytics = plugin
    ctx.on_reset(plugin.reset)
    ctx.on_event(plugin.on_event)
    ctx.on_tracking(plugin.on_tracking)
    ctx.on_control(plugin.on_control)
