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


def test_fast_stage_selection_keeps_semantic_verification(inputs):
    class Fast(Writer):
        name = "fake-fast"

        async def complete(self, system, user, json_schema=None):
            if "task" not in json.loads(user):
                self.calls.append(json.loads(user))
                return json.dumps({"status": "approved", "reason_code": None, "detail": "supported"}), 3
            return await super().complete(system, user, json_schema)

    class Strong:
        name = "unused-strong"

        async def complete(self, *args, **kwargs):
            raise AssertionError("The strong model must not run when both roles select fast")

    async def go():
        config = replace(AgentConfig(mode="stub"), analyst_model_role="fast", verifier_model_role="fast")
        fast = Fast()
        runner, moment, names, emitted = execute(inputs, config=config, model=fast)
        runner.strong = Strong()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.verification_status == "approved" for o in emitted)
        assert len(fast.calls) == 13  # Analyst + 6 writers + 6 semantic checks
        assert runner.ctx.budget.used == 18
    asyncio.run(go())


def test_model_role_configuration_validated(monkeypatch):
    assert AgentConfig().analyst_model_role == AgentConfig().verifier_model_role == "strong"
    for stage in ("ANALYST", "VERIFIER"):
        key = f"AGENT_{stage}_MODEL_ROLE"
        monkeypatch.setenv(key, "fast")
        assert getattr(AgentConfig.from_env(), f"{stage.lower()}_model_role") == "fast"
        monkeypatch.setenv(key, "unknown")
        with pytest.raises(ValueError, match=key):
            AgentConfig.from_env()
        monkeypatch.delenv(key)


def test_compact_writer_keeps_code_owned_facts(inputs):
    async def go():
        model = Writer()
        runner, moment, names, emitted = execute(inputs, model=model)
        await runner.run(moment, names)
        assert all(p["template"]["fields"] == {} for p in model.calls)
        assert all(all(o.fields[k] == v for k, v in moment.verified_facts.items()) for o in emitted)
    asyncio.run(go())


def test_semantic_checker_receives_metadata_names(inputs):
    class Semantic(StubModel):
        name = "semantic-fake"

        async def complete(self, system, user, json_schema=None):
            payload = json.loads(user)
            if payload.get("task") == "analyst":
                return await super().complete(system, user, json_schema)
            assert payload["names"]["nil_10"]["name"] == "Hassan Nour"
            assert payload["names"]["nil_10"]["name_ar"] == "حسن نور"
            assert payload["names"]["nil_07"]["name"] == "Seif Wahba"
            return json.dumps({"status": "approved", "reason_code": None, "detail": "supported"}), 1

    async def go():
        runner, moment, names, emitted = execute(inputs)
        runner.strong = Semantic()
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.verification_status == "approved" for o in emitted)
    asyncio.run(go())


def test_prepare_initializes_only_active_models_without_inference(inputs):
    events = []

    class Prepared(Writer):
        async def prepare(self):
            events.append("fast")

    class Unused(Writer):
        async def prepare(self):
            raise AssertionError("Unused strong model should stay lazy")

    async def go():
        config = replace(AgentConfig(mode="stub"), analyst_model_role="fast", verifier_model_role="fast")
        model = Prepared()
        runner, _, _, _ = execute(inputs, config=config, model=model)
        runner.strong = Unused()
        await runner.prepare()
        assert events == ["fast"] and not model.calls
    asyncio.run(go())


def test_foundry_prepare_authenticates_without_model_call():
    from backend.agents.llm import FoundryModel
    scopes = []

    class Credential:
        async def get_token(self, scope):
            scopes.append(scope)

    class Client:
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Startup must not call a model")

    async def go():
        model = FoundryModel("https://test.services.ai.azure.com/api/projects/test", "fast", client=Client())
        model._credential = Credential()
        await model.prepare()
        assert scopes == ["https://ai.azure.com/.default"]
    asyncio.run(go())


def test_fast_only_workflow_does_not_require_strong_deployment(inputs):
    from backend.agents.workflow import WorkflowRunner
    moment, _ = inputs
    config = AgentConfig(mode="foundry", foundry_project_endpoint="https://test.services.ai.azure.com/api/projects/test",
                         model_fast="configured-fast", analyst_model_role="fast", verifier_model_role="fast")
    runner = WorkflowRunner(SimpleNamespace(), config, tools=Tools(moment), framework=False)
    assert runner.fast.name == "configured-fast" and runner.strong is None


@pytest.mark.parametrize("body", ["A fast shot.", "A slow shot.", "تسديدة سريعة", "تسديدة بطيئة"])
def test_unclassified_shot_speed_rejected_before_semantic_call(inputs, body):
    from backend.agents.templates import template_overlays
    from backend.agents.verifier import brief_from_moment, verify_with_model

    class MustNotRun:
        name = "fake-semantic"

        async def complete(self, *args, **kwargs):
            raise AssertionError("Unsupported classification must be rejected in code")

    async def go():
        moment, names = inputs
        overlay = next(o for o in template_overlays(moment, names) if o.persona == "tactical" and o.language == "en")
        draft = overlay.model_copy(update={"body": body}).model_dump()
        budget = DailyTokenBudget(100000)
        verdict = await verify_with_model(draft, brief_from_moment(moment), moment, names, "tactical",
                                          model=MustNotRun(), budget=budget)
        assert verdict.reason_code == "UNSUPPORTED_CAUSALITY" and budget.used == 0
    asyncio.run(go())


def test_explicit_shot_speed_classification_is_allowed(inputs):
    from backend.agents.templates import template_overlays
    from backend.agents.verifier import brief_from_moment, verify
    moment, names = inputs
    moment = moment.model_copy(update={"verified_facts": {**moment.verified_facts, "shot_speed_classification": "fast"}})
    overlay = next(o for o in template_overlays(moment, names) if o.persona == "tactical" and o.language == "en")
    draft = overlay.model_copy(update={"body": "A fast shot."}).model_dump()
    assert verify(draft, brief_from_moment(moment), moment, names, "tactical").status == "approved"


def test_replay_delivers_agent_overlay_through_websocket(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import create_app
    from tests.test_api import make_settings, collect

    monkeypatch.setenv("AGENT_MODE", "stub")
    settings = make_settings(tmp_path, plugins=["backend.analytics.plugin:register", "backend.agents.plugin:register"])
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/ws/matches/match_001?persona=tactical&lang=ar&tracking_hz=0") as ws:
            response = client.post("/api/matches/match_001/start", params={"speed": 20, "from_minute": 63})
            assert response.status_code == 200
            try:
                messages = collect(ws, lambda items: any(m["type"] == "overlay" and m["data"]["moment_id"] == "mom_044" for m in items))
                overlay = next(m["data"] for m in messages if m["type"] == "overlay" and m["data"]["moment_id"] == "mom_044")
                assert overlay["source"] == "agent" and overlay["verification_status"] == "approved"
                assert (overlay["language"], overlay["dir"], overlay["show_at_s"]) == ("ar", "rtl", 3783)
                assert client.app.state.ctx.errors == 0
            finally:
                client.post("/api/matches/match_001/stop", headers={"X-Control-Token": response.json()["control_token"]})
