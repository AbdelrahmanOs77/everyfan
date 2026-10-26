"""Subscribe after analytics; schedule bounded workflows outside the consumer loop."""

import asyncio
import logging
import os
import time
from collections import OrderedDict

from .config import AgentConfig
from .names import NameAllowlist
from .producer import produce
from .workflow import WorkflowRunner


class AgentsPlugin:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.config = AgentConfig.from_env()
        self.runner = WorkflowRunner(ctx, self.config)
        self.names: dict[str, NameAllowlist] = {}
        self.seen: dict[str, set[str]] = {}
        self.generations: dict[str, int] = {}
        self.recaps: OrderedDict = OrderedDict()
        self._build_slots: asyncio.Semaphore | None = None

    def status(self) -> dict:
        def model(m):
            return None if m is None else {"deployment": getattr(m, "name", None), "auth": getattr(m, "auth", None)}
        c = self.config
        return {"mode": c.mode, "club_persona": c.club_persona,
                "tools": {"transport": type(self.runner.tools).__name__, "mcp_calls": getattr(self.runner.tools, "calls", None)}, "fast": model(self.runner.fast),
                "strong": model(self.runner.strong), "analyst_model_role": c.analyst_model_role,
                "verifier_model_role": c.verifier_model_role, "framework": self.runner.framework,
                "deadlines_s": {"producer": c.producer_timeout_s, "analyst": c.analyst_timeout_s,
                                "writer": c.writer_timeout_s, "verifier": c.verifier_timeout_s,
                                "total": c.total_timeout_s},
                "cached_overlays": len(self.runner.cache), "cached_recaps": len(self.recaps)}

    async def recap(self, meta, overlays: list[dict], *, persona: str, language: str, club_id: str | None = None,
                    until_s: float = 5400, cache_key=None, use_model: bool = True):
        """Recap agent (strong model when configured) with a checked deterministic fallback."""
        from .recap import build_recap

        key = (cache_key, persona, language, club_id, int(until_s), len(overlays))
        if cache_key is not None and key in self.recaps:
            self.recaps.move_to_end(key)
            return self.recaps[key]
        model = (self.runner.strong or self.runner.fast) if use_model else None
        result = await build_recap(meta, overlays, persona=persona, language=language, club_id=club_id,
                                   until_s=until_s, model=model, budget=self.ctx.budget)
        if cache_key is not None:
            self.recaps[key] = result
            while len(self.recaps) > 256:
                self.recaps.popitem(last=False)
        return result

    def reset(self, state) -> None:
        self.names[state.match_id] = NameAllowlist(state.metadata)
        self.seen[state.match_id] = set()
        self.generations[state.match_id] = self.generations.get(state.match_id, 0) + 1
        for key in list(self.runner.history):
            if key[0] == state.match_id:
                del self.runner.history[key]

    async def record_recaps(self, meta, overlays: list[dict]) -> dict[str, dict]:
        """Demo build: Recap agent output for every persona/language/club, stored in the bundle.

        Only checked agent recaps are kept; anything else is rebuilt deterministically at request time.
        """
        from .templates import ALL_PERSONAS, LANGUAGES

        out = {}
        for persona in ALL_PERSONAS:
            for club in ((meta.home.team_id, meta.away.team_id) if persona == "club" else (None,)):
                for lang in LANGUAGES:
                    recap = await self.recap(meta, overlays, persona=persona, language=lang, club_id=club)
                    if recap.source == "agent":
                        out[f"{persona}|{lang}|{club or ''}"] = {**recap.model_dump(), "feed_source": "demo",
                                                                 "run_id": None}
        return out

    async def _build_run(self, moment, names, plan, current, trace):
        """Demo build pacing: bounded concurrency, and AGENT_BUILD_TPM keeps token use under the deployment's
        tokens-per-minute quota so the recording is not full of rate-limit (429) fallbacks."""
        if self._build_slots is None:
            self._build_slots = asyncio.Semaphore(max(1, int(os.getenv("AGENT_BUILD_CONCURRENCY", "2"))))
            self._build_started = time.monotonic()
        tpm = float(os.getenv("AGENT_BUILD_TPM", "0") or 0)
        async with self._build_slots:
            if tpm > 0:
                used = getattr(self.ctx.budget, "used", 0)
                ahead = used / tpm * 60 - (time.monotonic() - self._build_started)
                if ahead > 0:
                    await asyncio.sleep(ahead)
            return await self.runner.run(moment, names, plan=plan, started=time.monotonic(),
                                         current=current, workflow_trace=trace)

    def on_moment(self, moment, state) -> None:
        started = time.monotonic()
        if moment.importance < 0.5:
            return
        if moment.match_id not in self.names:
            self.reset(state)
        seen = self.seen[moment.match_id]
        if moment.moment_id in seen:
            return
        seen.add(moment.moment_id)
        generation = self.generations[moment.match_id]
        names = self.names[moment.match_id]
        # Reserve air slots in event order, before asynchronous work can interleave.
        trace = self.runner.start_trace(moment, "analytics_callback")
        try:
            with trace.activate():
                with self.runner.telemetry.span("agent.producer") as span:
                    clubs = tuple(names.teams) if self.config.club_persona else ()
                    plan = produce(moment, self.runner.history, clubs)
                    span.set(count=len(plan))
                current = lambda: self.generations.get(moment.match_id) == generation  # noqa: E731
                if getattr(self.ctx, "recording", None) is not None and self.config.mode != "off":
                    # Demo build (offline, not real time): bounded concurrency so the model service is not
                    # flooded, and each workflow's clock starts when it actually runs.
                    task = self.ctx.spawn(self._build_run(moment, names, plan, current, trace))
                else:
                    task = self.ctx.spawn(self.runner.run(moment, names, plan=plan, started=started,
                                          current=current, workflow_trace=trace))
                task.add_done_callback(lambda _: trace.end())
        except BaseException:
            trace.end()
            raise


def register(ctx) -> None:
    if not hasattr(ctx, "analytics"):
        raise RuntimeError("Load backend.analytics.plugin:register before backend.agents.plugin:register")
    if "backend.api.template_plugin:register" in getattr(ctx, "loaded_plugins", []):
        logging.getLogger(__name__).warning("template_plugin and agents plugin both loaded: goals will air twice; "
                                            "remove backend.api.template_plugin:register from PIPELINE_PLUGINS")
    plugin = AgentsPlugin(ctx)
    ctx.agents = plugin
    ctx.on_reset(plugin.reset)
    ctx.analytics.subscribe(plugin.on_moment)
