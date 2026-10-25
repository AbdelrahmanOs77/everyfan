"""Offline workflow safety, repair and deadline coverage."""

import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.agents.config import AgentConfig
from backend.agents.llm import StubModel
from backend.agents.names import NameAllowlist
from backend.services.budget import DailyTokenBudget
from tests.test_agents_generation import Tools
from tests.test_agents_templates import ROWS, eval_moment


@pytest.fixture
def inputs(derby):
    moment = eval_moment(next(r for r in ROWS if r["match_id"] == "match_001" and r["moment_id"] == "mom_044"))
    return moment, NameAllowlist(derby.metadata)


class Writer(StubModel):
    def __init__(self, bad="never", delay=0):
        self.bad, self.delay, self.calls = bad, delay, []

    async def complete(self, system, user, json_schema=None):
        payload = json.loads(user)
        self.calls.append(payload)
        await asyncio.sleep(self.delay)
        text, usage = await super().complete(system, user, json_schema)
        if payload.get("task") == "writer" and (self.bad == "always" or self.bad == "first" and "repair_reason" not in payload):
            data = json.loads(text)
            data["body"] = "999999"
            text = json.dumps(data)
        return text, usage


def execute(inputs, model=None, config=None, cap=500000, framework=False):
    from backend.agents.workflow import WorkflowRunner

    moment, names = inputs
    emitted = []

    async def publish(overlay):
        emitted.append(overlay)

    ctx = SimpleNamespace(budget=DailyTokenBudget(cap), publish_overlay=publish)
    runner = WorkflowRunner(ctx, config or AgentConfig(mode="stub"), tools=Tools(moment),
                            fast=model or Writer(), strong=StubModel(), framework=framework)
    return runner, moment, names, emitted


@pytest.mark.parametrize("framework", [False, True])
def test_goal_approved_in_both_runtimes(inputs, framework):
    async def go():
        runner, moment, names, emitted = execute(inputs, framework=framework)
        await runner.run(moment, names)
        assert len(emitted) == 6
        assert all(o.source == "agent" and o.verification_status == "approved" for o in emitted)
        assert all(o.fields["attempts"] == 1 for o in emitted)
        assert runner.ctx.budget.reserved == 0
    asyncio.run(go())


@pytest.mark.parametrize("bad,source,attempts", [("first", "agent", 2), ("always", "template", 2)])
@pytest.mark.parametrize("framework", [False, True])
def test_one_repair_then_approve_or_fallback(inputs, bad, source, attempts, framework):
    async def go():
        model = Writer(bad)
        runner, moment, names, emitted = execute(inputs, model=model, framework=framework)
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.source == source for o in emitted)
        assert all("999999" not in o.body and o.fields["attempts"] == attempts for o in emitted)
        repairs = [p for p in model.calls if "repair_reason" in p]
        assert len(repairs) == 6
        assert all(p["repair_reason"] == "NUMBER_NOT_IN_EVIDENCE" for p in repairs)
    asyncio.run(go())


def test_total_deadline_falls_back_and_settles(inputs):
    async def go():
        config = replace(AgentConfig(mode="stub"), total_timeout_s=.08)
        runner, moment, names, emitted = execute(inputs, model=Writer(delay=1), config=config)
        started = time.monotonic()
        await runner.run(moment, names)
        assert time.monotonic() - started < .5
        assert len(emitted) == 6 and all(o.source == "template" for o in emitted)
        assert runner.ctx.budget.reserved == 0
    asyncio.run(go())


def test_empty_budget_never_calls_models(inputs):
    async def go():
        model = Writer()
        runner, moment, names, emitted = execute(inputs, model=model, cap=0)
        await runner.run(moment, names)
        assert not model.calls and not runner.tools.calls
        assert len(emitted) == 6 and all(o.source == "template" for o in emitted)
    asyncio.run(go())


def test_memory_cache_reused_with_no_budget_and_rechecked(inputs):
    async def go():
        model = Writer()
        runner, moment, names, emitted = execute(inputs, model=model)
        await runner.run(moment, names)
        calls = len(model.calls)
        emitted.clear()
        runner.ctx.budget = DailyTokenBudget(0)
        await runner.run(moment, names)
        assert len(model.calls) == calls
        assert len(emitted) == 6 and all(o.source == "agent" and o.fields["reason_codes"] == "CACHE" for o in emitted)
        for overlay in runner.cache.values():
            overlay["body"] = "999999"
        emitted.clear()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.source == "template" for o in emitted)
    asyncio.run(go())


def test_demo_cache_uses_fingerprint_and_refuses_stale_bundle(inputs, derby):
    from backend.api.demo import DemoBundle, DemoStore, fingerprint

    async def go():
        runner, moment, names, emitted = execute(inputs)
        await runner.run(moment, names)
        bundle = DemoBundle(moment.match_id, "derby_balanced", fingerprint(derby.events), [],
                            [{"type": "overlay", "data": o.model_dump()} for o in emitted])
        demo = object.__new__(DemoStore)
        demo.bundles = {moment.match_id: bundle}

        class Library:
            async def get(self, match_id):
                return derby

        runner.ctx.demo, runner.ctx.library = demo, Library()
        runner.ctx.budget = DailyTokenBudget(0)
        runner.cache.clear()
        emitted.clear()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.fields["reason_codes"] == "CACHE" for o in emitted)
        runner.cache.clear()
        bundle.fingerprint = "obsolete"
        emitted.clear()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.source == "template" for o in emitted)
    asyncio.run(go())


def test_store_receives_briefs_approved_overlays_and_audit(inputs, monkeypatch):
    docs = []
    monkeypatch.setattr("backend.analytics.store.get_store", lambda: SimpleNamespace(enqueue=lambda kind, doc: docs.append((kind, doc))))

    async def go():
        runner, moment, names, _ = execute(inputs, model=Writer("first"))
        await runner.run(moment, names)
        assert len([d for kind, d in docs if kind == "briefs"]) == 1
        assert len([d for kind, d in docs if kind == "overlays"]) == 6
        audits = [d for kind, d in docs if kind == "audit"]
        assert len([d for d in audits if d["kind"] == "verdict"]) == 12
        assert len([d for d in audits if d["kind"] == "repair"]) == 6
        assert all(d["match_id"] == moment.match_id for _, d in docs)
    asyncio.run(go())


def test_reset_during_generation_never_publishes_or_persists(inputs, monkeypatch):
    docs = []
    monkeypatch.setattr("backend.analytics.store.get_store", lambda: SimpleNamespace(enqueue=lambda *args: docs.append(args)))

    async def go():
        runner, moment, names, emitted = execute(inputs, model=Writer(delay=.03))
        valid = True
        task = asyncio.create_task(runner.run(moment, names, current=lambda: valid))
        await asyncio.sleep(.01)
        valid = False
        await task
        assert not emitted and not docs and not runner.cache
    asyncio.run(go())


def test_framework_import_failure_uses_same_stages(inputs, monkeypatch):
    import backend.agents.workflow as workflow
    original = workflow.importlib.import_module

    def missing(name, *args, **kwargs):
        if name == "backend.agents.workflow_graph":
            raise ImportError("unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(workflow.importlib, "import_module", missing)

    async def go():
        runner, moment, names, emitted = execute(inputs, framework=True)
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.verification_status == "approved" for o in emitted)
    asyncio.run(go())


def test_semantic_rejection_repairs_then_falls_back(inputs):
    class Semantic(StubModel):
        name = "semantic_fake"

        async def complete(self, system, user, json_schema=None):
            if json.loads(user).get("task") == "analyst":
                return await super().complete(system, user, json_schema)
            return json.dumps({"status": "rejected", "reason_code": "UNSUPPORTED_CAUSALITY", "detail": "unsupported"}), 7

    async def go():
        runner, moment, names, emitted = execute(inputs)
        runner.strong = Semantic()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.source == "template" and o.fields["attempts"] == 2 for o in emitted)
        assert all("UNSUPPORTED_CAUSALITY" in o.fields["reason_codes"] for o in emitted)
        assert runner.ctx.budget.used == 84 and runner.ctx.budget.reserved == 0
    asyncio.run(go())


def test_insufficient_reservation_never_calls_models(inputs):
    async def go():
        model = Writer()
        runner, moment, names, emitted = execute(inputs, model=model, cap=1)
        await runner.run(moment, names)
        assert not model.calls and len(emitted) == 6
        assert runner.ctx.budget.used == runner.ctx.budget.reserved == 0
    asyncio.run(go())


def test_repair_isolated_to_rejected_writer(inputs):
    class OneBad(Writer):
        async def complete(self, system, user, json_schema=None):
            payload = json.loads(user)
            text, usage = await super().complete(system, user, json_schema)
            if (payload.get("persona"), payload.get("language")) == ("tactical", "ar") and "repair_reason" not in payload:
                text = json.dumps({**json.loads(text), "body": "999999"})
            return text, usage

    async def go():
        model = OneBad()
        runner, moment, names, emitted = execute(inputs, model=model, framework=True)
        await runner.run(moment, names)
        assert len(model.calls) == 7
        assert len(emitted) == 6 and all(o.verification_status == "approved" for o in emitted)
        assert {(o.persona, o.language) for o in emitted if o.fields["attempts"] == 2} == {("tactical", "ar")}
    asyncio.run(go())


def test_writer_exception_and_stage_timeout_fall_back_without_repair(inputs):
    class Broken(Writer):
        async def complete(self, *args, **kwargs):
            self.calls.append("broken")
            raise RuntimeError("transport")

    async def go():
        for model in [Broken(), Writer(delay=.1)]:
            config = replace(AgentConfig(mode="stub"), writer_timeout_s=.01)
            runner, moment, names, emitted = execute(inputs, model=model, config=config)
            await runner.run(moment, names)
            assert len(emitted) == 6 and all(o.source == "template" and o.fields["attempts"] == 1 for o in emitted)
            assert len(model.calls) == 6 and runner.ctx.budget.reserved == 0
    asyncio.run(go())


def test_external_cancellation_settles_without_publication(inputs):
    async def go():
        model = Writer(delay=1)
        runner, moment, names, emitted = execute(inputs, model=model)
        task = asyncio.create_task(runner.run(moment, names))
        while not model.calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not emitted and runner.ctx.budget.reserved == 0
    asyncio.run(go())


def test_receipt_clock_includes_queue_delay(inputs):
    async def go():
        model = Writer()
        runner, moment, names, emitted = execute(inputs, model=model)
        await runner.run(moment, names, started=time.monotonic() - 1)
        assert not model.calls and len(emitted) == 6
        assert all(o.fields["reason_codes"] == "PRODUCER_TIMEOUT" for o in emitted)
    asyncio.run(go())


def test_model_shutdown_follows_live_stop():
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.agents.mcp_server import mount_mcp

    events = []

    async def drain(**kwargs):
        events.append("drain")

    async def close():
        events.append("close")

    @asynccontextmanager
    async def lifespan(app):
        app.state.library = object()
        app.state.ctx = SimpleNamespace(drain=drain, agents=SimpleNamespace(
            config=AgentConfig(), runner=SimpleNamespace(aclose=close)))
        yield
        events.append("live_stop")

    app = FastAPI(lifespan=lifespan)
    mount_mcp(app)
    with TestClient(app):
        assert events == []
    assert events == ["live_stop", "drain", "close"]
