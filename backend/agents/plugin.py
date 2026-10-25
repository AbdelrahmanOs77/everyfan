"""Subscribe after analytics; keep template publishing outside the consumer loop."""

from .config import AgentConfig
from .names import NameAllowlist
from .templates import template_overlays


class AgentsPlugin:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.config = AgentConfig.from_env()
        self.names: dict[str, NameAllowlist] = {}
        self.seen: dict[str, set[str]] = {}
        self.generations: dict[str, int] = {}

    def reset(self, state) -> None:
        self.names[state.match_id] = NameAllowlist(state.metadata)
        self.seen[state.match_id] = set()
        self.generations[state.match_id] = self.generations.get(state.match_id, 0) + 1

    def on_moment(self, moment, state) -> None:
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
        self.ctx.spawn(self.publish(moment, names, generation))

    async def publish(self, moment, names, generation) -> None:
        for overlay in template_overlays(moment, names):
            if self.generations.get(moment.match_id) != generation:
                return  # a replay reset invalidated the pending run
            await self.ctx.publish_overlay(overlay)


def register(ctx) -> None:
    if not hasattr(ctx, "analytics"):
        raise RuntimeError("Load backend.analytics.plugin:register before backend.agents.plugin:register")
    plugin = AgentsPlugin(ctx)
    ctx.agents = plugin
    ctx.on_reset(plugin.reset)
    ctx.analytics.subscribe(plugin.on_moment)
