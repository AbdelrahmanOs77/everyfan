"""Agent Framework 1.23 graph; optional import keeps the async fallback independent."""

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from .workflow import Run


class Stage(Executor):
    def __init__(self, name, action):
        super().__init__(id=name)
        self.action = action

    @handler
    async def process(self, run: Run, ctx: WorkflowContext[Run]) -> None:
        await self.action(run)
        await ctx.send_message(run)


async def execute(runner, run):
    analyst = Stage("analyst", runner.analyst)
    writers = Stage("writers", runner.writers)
    verifier = Stage("verifier", runner.verifier)

    async def repair_action(state):
        await runner.writers(state, repair=True)

    repair = Stage("repair_same_writer", repair_action)
    graph = (WorkflowBuilder(start_executor=analyst)
             .add_edge(analyst, writers)
             .add_edge(writers, verifier)
             .add_edge(verifier, repair, condition=lambda state: bool(state.repair))
             .add_edge(repair, verifier)
             .build())
    await graph.run(run)
