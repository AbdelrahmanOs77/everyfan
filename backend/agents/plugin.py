"""Subscribe after analytics; schedule bounded workflows outside the consumer loop."""

import time

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

    def reset(self, state) -> None:
        self.names[state.match_id] = NameAllowlist(state.metadata)
        self.seen[state.match_id] = set()
        self.generations[state.match_id] = self.generations.get(state.match_id, 0) + 1
        for key in list(self.runner.history):
            if key[0] == state.match_id:
                del self.runner.history[key]

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
        plan = produce(moment, self.runner.history)
        self.ctx.spawn(self.runner.run(moment, names, plan=plan, started=started,
                                       current=lambda: self.generations.get(moment.match_id) == generation))


def register(ctx) -> None:
    if not hasattr(ctx, "analytics"):
        raise RuntimeError("Load backend.analytics.plugin:register before backend.agents.plugin:register")
    plugin = AgentsPlugin(ctx)
    ctx.agents = plugin
    ctx.on_reset(plugin.reset)
    ctx.analytics.subscribe(plugin.on_moment)
