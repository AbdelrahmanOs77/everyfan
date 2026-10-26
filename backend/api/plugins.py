"""Pipeline plugins: how analytics (Owner B) and agents (Owner C) join the live stream.

A plugin is a function `register(ctx: PipelineContext)` named in PIPELINE_PLUGINS, e.g.
    PIPELINE_PLUGINS=backend.analytics.plugin:register,backend.agents.plugin:register

    def register(ctx):
        @ctx.on_event
        async def handle(event, state):            # every SyntheticEvent, in order, exactly once
            moment = detector.update(event)
            if moment:
                await ctx.publish_moment(moment)    # Contract B -> viewers + demo bundle
                ctx.spawn(explain(moment))          # slow work (model calls) in the background

        async def explain(moment):
            if not await ctx.budget.try_reserve(1500):
                await ctx.publish_overlay(template_overlay(moment)); return
            ...
            await ctx.publish_overlay(overlay)      # Contract C, validated before it is sent

Handlers run inline in the consumer, so keep them fast and use ctx.spawn() for anything slow.
The same plugins run when building the cached demo match (`python -m backend.cli build-demo`).
"""

from __future__ import annotations

import asyncio
import importlib
from collections import deque
import inspect
import logging
from typing import Any, Callable

from shared.schemas import Moment, Overlay

from backend.services.budget import DailyTokenBudget

from .hub import ViewerHub, message

log = logging.getLogger("everyfan.plugins")


class PipelineContext:
    def __init__(self, hub: ViewerHub, budget: DailyTokenBudget, settings=None, library=None) -> None:
        self.hub, self.budget, self.settings, self.library = hub, budget, settings, library
        self.event_handlers: list[Callable] = []
        self.tracking_handlers: list[Callable] = []
        self.reset_handlers: list[Callable] = []
        self.control_handlers: list[Callable] = []
        self.recording: list[dict] | None = None  # set by the demo builder
        self.run_ids: dict[str, str] = {}
        self.errors = 0
        self._tasks: set[asyncio.Task] = set()
        self.loaded_plugins: list[str] = []
        # Public overlay feed: every overlay published in the current run of each match.
        self.overlay_log: dict[str, tuple[str | None, deque]] = {}

    # registration (usable as decorators)
    def on_event(self, fn): self.event_handlers.append(fn); return fn
    def on_tracking(self, fn): self.tracking_handlers.append(fn); return fn
    def on_reset(self, fn): self.reset_handlers.append(fn); return fn
    def on_control(self, fn): self.control_handlers.append(fn); return fn

    async def dispatch(self, handlers: list[Callable], *args) -> None:
        for fn in handlers:
            try:
                result = fn(*args)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # a plugin bug must never stop the match
                self.errors += 1
                log.exception("plugin handler %s failed", getattr(fn, "__name__", fn))

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(self._guard(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _guard(self, coro) -> Any:
        try:
            return await coro
        except Exception:
            self.errors += 1
            log.exception("background plugin task failed")

    async def drain(self, timeout: float = 600) -> None:
        """Wait for every spawned task (used by the demo builder)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self._tasks and asyncio.get_running_loop().time() < deadline:
            await asyncio.wait(list(self._tasks), timeout=1)

    # outputs
    async def publish_moment(self, moment: Moment | dict) -> Moment:
        moment = Moment.model_validate(moment)
        self._emit("moment", moment.match_id, moment.game_clock_s, moment.model_dump(exclude_none=True))
        return moment

    async def publish_overlay(self, overlay: Overlay | dict) -> Overlay:
        overlay = Overlay.model_validate(overlay)
        data = overlay.model_dump(exclude_none=True)
        self._log_overlay(overlay.match_id, data)
        self._emit("overlay", overlay.match_id, overlay.show_at_s, data)
        return overlay

    def _log_overlay(self, match_id: str, data: dict) -> None:
        run_id = self.run_ids.get(match_id)
        current = self.overlay_log.get(match_id)
        if current is None or current[0] != run_id:  # a new replay or seek starts a fresh feed
            current = (run_id, deque(maxlen=5000))
            self.overlay_log[match_id] = current
        current[1].append(data)

    def overlays(self, match_id: str) -> tuple[str | None, list[dict]]:
        """(run_id, overlays) published so far in the current run of a match."""
        run_id, items = self.overlay_log.get(match_id, (None, ()))
        if run_id != self.run_ids.get(match_id):
            return self.run_ids.get(match_id), []
        return run_id, list(items)

    def _emit(self, kind: str, match_id: str, t: float, data: dict) -> None:
        msg = message(kind, match_id, self.run_ids.get(match_id), t, data)
        self.hub.channel(match_id).publish(msg)
        if self.recording is not None:
            self.recording.append({"type": kind, "game_time_s": float(t), "data": data})

    def status(self) -> dict:
        return {"plugins": self.loaded_plugins, "background_tasks": len(self._tasks), "errors": self.errors}


def load_plugins(ctx: PipelineContext, specs: list[str]) -> None:
    for spec in specs:
        module_name, _, func = spec.partition(":")
        try:
            module = importlib.import_module(module_name)
            getattr(module, func or "register")(ctx)
            ctx.loaded_plugins.append(spec)
            log.info("loaded plugin %s", spec)
        except Exception:
            ctx.errors += 1
            log.exception("could not load plugin %s", spec)
