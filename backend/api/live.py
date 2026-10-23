"""Live mode: replays published to the stream (Event Hubs in Azure), consumed back, run through the
pipeline plugins and fanned out to viewers with the broadcast delay.

One live broadcast per match, shared by every viewer (like TV). Whoever starts it gets a
control token; only that token (or ADMIN_TOKEN) can pause, seek or change speed while it runs.
A broadcast with no viewers for IDLE_STOP_S is stopped to save model tokens.
If Event Hubs is unreachable the service falls back to the in-process bus and says so in /api/health.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass

from backend.services.consumer import MatchStateConsumer
from backend.services.stream import default_bus, make_publisher, make_subscriber
from backend.simulator.replay import ReplayController

from . import feed
from .hub import ViewerHub
from .library import MatchLibrary
from .plugins import PipelineContext
from .settings import Settings

log = logging.getLogger("everyfan.live")


class LiveError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class LiveRun:
    ctrl: ReplayController
    task: asyncio.Task
    control_token: str
    started_by: str
    started_at: float

    @property
    def active(self) -> bool:
        return not self.task.done() and self.ctrl.state in ("running", "paused", "idle")


class LiveService:
    def __init__(self, settings: Settings, library: MatchLibrary, hub: ViewerHub, ctx: PipelineContext) -> None:
        self.settings, self.library, self.hub, self.ctx = settings, library, hub, ctx
        self.transport = settings.transport
        self.fallback_reason: str | None = None
        self.runs: dict[str, LiveRun] = {}
        self.consumer = MatchStateConsumer(on_reset=self._on_reset, on_event=self._on_event,
                                           on_tracking=self._on_tracking, on_control=self._on_control)
        self._subscriber = None
        self._consumer_task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._last_replay_push: dict[str, float] = {}

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        await self._start_consumer()
        self._watchdog = asyncio.create_task(self._watch())

    async def _start_consumer(self) -> None:
        if self.transport == "eventhubs" and not await self._eventhubs_ok():
            self._fallback(self.fallback_reason or "Event Hubs probe failed")
        self._subscriber = make_subscriber(self.transport, bus=default_bus())
        self._consumer_task = asyncio.create_task(self._consume())
        if self.transport == "eventhubs":
            await asyncio.sleep(3)  # let the receiver attach at "@latest" before anything is published

    async def _eventhubs_ok(self) -> bool:
        """Probe both directions: catches bad names, missing roles and auth problems in seconds."""
        clients = []
        try:
            clients = [make_publisher("eventhubs"), make_subscriber("eventhubs")]
            await asyncio.wait_for(asyncio.gather(*(c.probe() for c in clients)), timeout=15)
            return True
        except Exception as exc:
            self.fallback_reason = f"Event Hubs unavailable: {type(exc).__name__}: {str(exc)[:200]}"
            return False
        finally:
            for c in clients:
                try:
                    await c.close()
                except Exception:
                    pass

    async def _try_restore(self) -> None:
        """Self-healing: once Event Hubs works again (e.g. a new role assignment propagated), switch back."""
        if self.settings.transport != "eventhubs" or self.transport == "eventhubs" or self.active_count():
            return
        if not await self._eventhubs_ok():
            return
        old_task, old_sub = self._consumer_task, self._subscriber
        self.transport, self.fallback_reason = "eventhubs", None
        self._subscriber = make_subscriber("eventhubs")
        self._consumer_task = asyncio.create_task(self._consume())
        log.info("Event Hubs reachable again: live mode is back on Event Hubs")
        if old_task:
            old_task.cancel()
        if old_sub:
            try:
                await old_sub.close()
            except Exception:
                pass

    async def _consume(self) -> None:
        try:
            await self.consumer.consume(self._subscriber)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("stream consumer failed")
            if self.transport != "local":
                self._fallback(f"consumer: {exc}")
                self._subscriber = make_subscriber("local", bus=default_bus())
                self._consumer_task = asyncio.create_task(self._consume())

    def _fallback(self, reason: str) -> None:
        log.error("falling back to the local bus: %s", reason)
        self.transport, self.fallback_reason = "local", reason

    async def stop(self) -> None:
        for run in self.runs.values():
            run.ctrl.stop()
        await asyncio.gather(*(r.task for r in self.runs.values()), return_exceptions=True)
        for task in (self._watchdog, self._consumer_task):
            if task:
                task.cancel()
        if self._subscriber:
            try:
                await self._subscriber.close()
            except Exception:
                pass

    async def _watch(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(5)
            ticks += 1
            if ticks % 12 == 0:  # every minute
                await self._try_restore()
            for match_id, run in list(self.runs.items()):
                if run.active:
                    self.hub.channel(match_id).publish(feed.replay_msg(match_id, run.ctrl.status(), "live"))
                    if self.hub.channel(match_id).idle_for() > self.settings.idle_stop_s:
                        log.info("stopping idle live replay %s", match_id)
                        run.ctrl.stop()

    # ---------------------------------------------------- consumer callbacks

    async def _on_reset(self, state) -> None:
        self.ctx.run_ids[state.match_id] = state.run_id
        ch = self.hub.channel(state.match_id)
        ch.publish(feed.reset_msg(state))
        ch.publish(feed.metadata_msg(state))
        ch.publish(feed.state_msg(state))
        await self.ctx.dispatch(self.ctx.reset_handlers, state)

    async def _on_event(self, e, state) -> None:
        ch = self.hub.channel(state.match_id)
        ch.publish(feed.event_msg(e, state))
        ch.publish(feed.state_msg(state))
        await self.ctx.dispatch(self.ctx.event_handlers, e, state)

    async def _on_tracking(self, f, state) -> None:
        self.hub.channel(state.match_id).publish(feed.tracking_msg(f, state))
        await self.ctx.dispatch(self.ctx.tracking_handlers, f, state)

    async def _on_control(self, c, state) -> None:
        ch = self.hub.channel(state.match_id)
        ch.publish(feed.control_msg(c, state))
        run = self.runs.get(state.match_id)
        if run:
            ch.publish(feed.replay_msg(state.match_id, run.ctrl.status(), "live"))
        await self.ctx.dispatch(self.ctx.control_handlers, c, state)

    # --------------------------------------------------------------- control

    def status(self, match_id: str) -> dict:
        run = self.runs.get(match_id)
        if not run:
            return {"match_id": match_id, "state": "idle", "mode": "live"}
        return {**run.ctrl.status(), "mode": "live", "started_at": run.started_at,
                "viewers": len(self.hub.channel(match_id).clients)}

    def state(self, match_id: str) -> dict | None:
        s = self.consumer.states.get(match_id)
        return s.to_dict() if s else None

    def active_count(self) -> int:
        return sum(1 for r in self.runs.values() if r.active)

    def _authorise(self, match_id: str, token: str | None, admin: bool) -> LiveRun:
        run = self.runs.get(match_id)
        if not run or not run.active:
            raise LiveError(404, "no live replay is running for this match")
        if not admin and not (token and secrets.compare_digest(token, run.control_token)):
            raise LiveError(423, "this broadcast is controlled by the viewer who started it")
        return run

    async def start_run(self, match_id: str, speed: float, from_minute: float, client: str, admin: bool,
                        token: str | None = None) -> dict:
        if not self.library.has(match_id):
            raise LiveError(404, f"unknown match {match_id}")
        if speed not in self.settings.allowed_speeds and not admin:
            raise LiveError(400, f"speed must be one of {self.settings.allowed_speeds}")
        if not 0 <= from_minute < 90:
            raise LiveError(400, "from_minute must be between 0 and 90")
        current = self.runs.get(match_id)
        if current and current.active:
            owner = token and secrets.compare_digest(token, current.control_token)
            if not (admin or owner):
                raise LiveError(409, "a live broadcast of this match is already running: join it on the WebSocket")
            current.ctrl.stop()
            await asyncio.gather(current.task, return_exceptions=True)
        elif self.active_count() >= self.settings.max_active_live and not admin:
            raise LiveError(503, "too many live broadcasts right now; try the cached demo match")

        match = await self.library.get(match_id)
        try:
            publisher = make_publisher(self.transport, bus=default_bus())
        except Exception as exc:
            self._fallback(f"publisher: {exc}")
            publisher = make_publisher("local", bus=default_bus())
        ctrl = ReplayController(match.metadata, match.events, match.frames, publisher, speed=speed,
                                start_at_s=from_minute * 60)
        token = secrets.token_urlsafe(18)
        task = asyncio.create_task(self._run(ctrl, publisher))
        self.runs[match_id] = LiveRun(ctrl, task, token, client, time.time())
        self.hub.channel(match_id).last_viewer_seen = time.monotonic()
        return {**self.status(match_id), "control_token": token}

    async def _run(self, ctrl: ReplayController, publisher) -> None:
        try:
            await ctrl.run()
        except Exception as exc:
            log.exception("live replay failed")
            if self.transport != "local":
                self._fallback(f"publish: {exc}")
        finally:
            try:
                await publisher.close()
            except Exception:
                pass

    def control(self, match_id: str, action: str, token: str | None, admin: bool, value: float | None = None) -> dict:
        run = self._authorise(match_id, token, admin)
        ctrl = run.ctrl
        if action == "pause":
            ctrl.pause()
        elif action == "resume":
            ctrl.resume()
        elif action == "stop":
            ctrl.stop()
        elif action == "speed":
            if value is None or (value not in self.settings.allowed_speeds and not admin):
                raise LiveError(400, f"speed must be one of {self.settings.allowed_speeds}")
            ctrl.set_speed(value)
        elif action == "seek":
            if value is None or not 0 <= value < 90:
                raise LiveError(400, "minute must be between 0 and 90")
            ctrl.seek(value * 60)
            if ctrl.state == "paused":
                ctrl.resume()
        else:
            raise LiveError(400, f"unknown action {action}")
        return self.status(match_id)
