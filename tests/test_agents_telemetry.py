"""Trace correlation, privacy and failures; exporters stay entirely local."""

import asyncio
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.agents.config import AgentConfig
from backend.agents.llm import StubModel
from backend.agents.names import NameAllowlist
from backend.services.budget import DailyTokenBudget
from tests.test_agents_generation import Tools
from tests.test_agents_templates import ROWS, eval_moment
from tests.test_agents_workflow import Writer


@pytest.fixture
def trace_case(derby):
    from backend.agents.telemetry import Telemetry
    moment = eval_moment(next(r for r in ROWS if r["match_id"] == "match_001" and r["moment_id"] == "mom_044"))
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield moment, NameAllowlist(derby.metadata), Telemetry(provider.get_tracer("everyfan-test")), exporter
    provider.shutdown()


def runner_for(case, *, fast=None, strong=None, framework=False, cap=500000):
    from backend.agents.workflow import WorkflowRunner
    moment, names, telemetry, exporter = case
    emitted = []

    async def publish(overlay):
        emitted.append(overlay)

    ctx = SimpleNamespace(budget=DailyTokenBudget(cap), publish_overlay=publish)
    runner = WorkflowRunner(ctx, AgentConfig(mode="stub"), tools=Tools(moment),
                            fast=fast or StubModel(), strong=strong or StubModel(),
                            framework=framework, telemetry=telemetry)
    return runner, moment, names, emitted, exporter


@pytest.mark.parametrize("framework", [False, True])
def test_goal_trace_has_agents_tools_and_overlay_correlation(trace_case, framework):
    async def go():
        runner, moment, names, emitted, exporter = runner_for(trace_case, framework=framework)
        await runner.run(moment, names)
        spans = exporter.get_finished_spans()
        roots = [s for s in spans if s.name == "everyfan.workflow"]
        assert len(roots) == 1
        root = roots[0]
        trace_id = format(root.context.trace_id, "032x")
        assert len(emitted) == 6 and all(o.trace_id == trace_id for o in emitted)
        assert all(s.context.trace_id == root.context.trace_id for s in spans)
        assert {"agent.producer", "agent.analyst", "agent.writer", "agent.verifier",
                "tool.get_moment_evidence", "tool.get_match_state", "model.complete"} <= {s.name for s in spans}
        assert len([s for s in spans if s.name == "agent.writer"]) == 6
        assert all(s.attributes["everyfan.moment_id"] == moment.moment_id for s in spans)
        assert root.attributes["everyfan.approved"] == 6
        assert root.attributes["everyfan.fallback"] == 0
        assert root.attributes["everyfan.entry_point"] == "direct"
        for span in spans:
            if span is not root:
                assert span.parent and span.parent.span_id in {s.context.span_id for s in spans}
    asyncio.run(go())


def test_tokens_are_aggregated_per_run_not_shared_budget(trace_case):
    class Counted(StubModel):
        async def complete(self, *args, **kwargs):
            text, _ = await super().complete(*args, **kwargs)
            return text, 7

    async def go():
        first = runner_for(trace_case, fast=Counted(), strong=Counted())
        second = runner_for(trace_case, fast=Counted(), strong=Counted())
        await asyncio.gather(first[0].run(first[1], first[2]), second[0].run(second[1], second[2]))
        roots = [s for s in first[-1].get_finished_spans() if s.name == "everyfan.workflow"]
        assert len(roots) == 2 and len({s.context.trace_id for s in roots}) == 2
        assert all(s.attributes["everyfan.tokens"] == 49 for s in roots)
    asyncio.run(go())


def test_repair_and_fallback_reasons_are_visible(trace_case):
    async def go():
        runner, moment, names, emitted, exporter = runner_for(trace_case, fast=Writer("always"))
        await runner.run(moment, names)
        spans = exporter.get_finished_spans()
        assert len(emitted) == 6 and all(o.source == "template" for o in emitted)
        assert len([s for s in spans if s.name == "agent.writer" and s.attributes["everyfan.attempts"] == 2]) == 6
        root = next(s for s in spans if s.name == "everyfan.workflow")
        events = [(e.name, dict(e.attributes)) for s in spans for e in s.events]
        assert any(n == "repair" and a["everyfan.reason_code"] == "NUMBER_NOT_IN_EVIDENCE" for n, a in events)
        assert root.attributes["everyfan.fallback"] == 6
    asyncio.run(go())


def test_model_error_does_not_export_exception_text_or_prompts(trace_case):
    secret = "private-api-key-and-prompt"

    class Broken(StubModel):
        async def complete(self, *args, **kwargs):
            raise RuntimeError(secret)

    async def go():
        runner, moment, names, emitted, exporter = runner_for(trace_case, fast=Broken())
        await runner.run(moment, names)
        spans = exporter.get_finished_spans()
        serialized = " ".join(s.to_json() for s in spans)
        assert secret not in serialized
        assert "Hassan Nour" not in serialized
        assert "verified_facts" not in serialized
        assert "RuntimeError" in serialized and len(emitted) == 6
    asyncio.run(go())


def test_no_connection_string_never_imports_exporter(monkeypatch):
    from backend.agents import telemetry
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    def unexpected(*args):
        raise AssertionError("Exporter must not initialize without a connection string")

    monkeypatch.setattr(telemetry, "_configure_exporter", unexpected)
    monkeypatch.setattr(telemetry, "_configured", False)
    instance = telemetry.configure()
    assert instance.tracer is None


def test_configure_once_and_redact_failure(monkeypatch, caplog):
    from backend.agents import telemetry
    secret = "InstrumentationKey=do-not-log-this"
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", secret)
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_default", telemetry.Telemetry())
    calls = []

    def broken(connection):
        calls.append(connection)
        raise ValueError(secret)

    monkeypatch.setattr(telemetry, "_configure_exporter", broken)
    assert telemetry.configure().tracer is None
    assert telemetry.configure().tracer is None
    assert len(calls) == 1 and secret not in caplog.text


def test_exporter_options_disable_message_capture_and_auto_instrumentation(monkeypatch):
    from backend.agents import telemetry
    import azure.monitor.opentelemetry
    import agent_framework.observability
    captured = {}
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "none")
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    monkeypatch.setattr(azure.monitor.opentelemetry, "configure_azure_monitor", lambda **kw: captured.update(kw))
    native = []
    monkeypatch.setattr(agent_framework.observability, "enable_instrumentation", lambda **kw: native.append(kw))
    telemetry._configure_exporter("fake-connection")
    assert captured["connection_string"] == "fake-connection"
    assert captured["disable_offline_storage"] is True
    assert captured["enable_live_metrics"] is False
    assert all(not config["enabled"] for config in captured["instrumentation_options"].values())
    assert native == [{"enable_sensitive_data": False, "enable_message_events": False}]


def test_configuration_success_is_idempotent(trace_case, monkeypatch):
    from backend.agents import telemetry
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "fake-not-exported")
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_default", telemetry.Telemetry())
    calls = []

    def configured(connection):
        calls.append(connection)
        return trace_case[2].tracer

    monkeypatch.setattr(telemetry, "_configure_exporter", configured)
    first = telemetry.configure()
    assert telemetry.configure() is first and len(calls) == 1


def test_trace_attributes_are_allowlisted(trace_case):
    _, _, telemetry, exporter = trace_case
    with telemetry.span("test", moment_id="mom_044", api_key="private-key", prompt="private-prompt") as span:
        span.set(verdict="approved", response="private-response")
        span.event("verdict", reason_code="TONE", detail="private-detail")
    data = exporter.get_finished_spans()[0].to_json()
    assert "mom_044" in data and "TONE" in data
    assert "private-" not in data


def test_tracer_failure_does_not_break_workflow(trace_case):
    from backend.agents.telemetry import Telemetry

    class Broken:
        def start_span(self, *args, **kwargs):
            raise RuntimeError("exporter unavailable")

    async def go():
        runner, moment, names, emitted, _ = runner_for(trace_case)
        runner.telemetry = Telemetry(Broken())
        await runner.run(moment, names)
        assert len(emitted) == 6 and all(o.trace_id for o in emitted)
    asyncio.run(go())


def test_cancellation_closes_trace_and_reports_unknown_usage(trace_case):
    async def go():
        model = Writer(delay=1)
        runner, moment, names, emitted, exporter = runner_for(trace_case, fast=model)
        task = asyncio.create_task(runner.run(moment, names))
        while not model.calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        spans = exporter.get_finished_spans()
        root = next(s for s in spans if s.name == "everyfan.workflow")
        assert root.attributes["everyfan.outcome"] == "cancelled"
        assert root.attributes["everyfan.tokens"] == 0
        assert root.attributes["everyfan.charged_tokens"] > 0
        assert runner.ctx.budget.reserved == 0 and not emitted
        assert any(s.attributes.get("everyfan.usage_unknown") for s in spans if s.name == "model.complete")
    asyncio.run(go())


@pytest.mark.parametrize("reset_before_run", [False, True])
def test_plugin_trace_includes_synchronous_producer_and_handles_reset(trace_case, monkeypatch, reset_before_run):
    from backend.agents.plugin import register
    from backend.api.plugins import PipelineContext
    from backend.api.hub import ViewerHub
    monkeypatch.setenv("AGENT_MODE", "stub")

    async def go():
        moment, names, telemetry, exporter = trace_case
        callbacks = []
        ctx = PipelineContext(ViewerHub(0), DailyTokenBudget(500000))
        ctx.analytics = SimpleNamespace(subscribe=callbacks.append)
        ctx.recording = []
        register(ctx)
        ctx.agents.runner.telemetry = telemetry
        ctx.agents.runner.tools = Tools(moment)
        state = SimpleNamespace(match_id=moment.match_id, metadata=names.meta)
        ctx.agents.reset(state)
        callbacks[0](moment, state)
        if reset_before_run:
            ctx.agents.reset(state)
        await ctx.drain()
        spans = exporter.get_finished_spans()
        root = next(s for s in spans if s.name == "everyfan.workflow")
        producer = next(s for s in spans if s.name == "agent.producer")
        assert producer.parent.span_id == root.context.span_id
        # Synchronous scheduling can finish within the Windows clock's resolution.
        assert root.start_time <= producer.start_time <= producer.end_time <= root.end_time
        assert root.attributes["everyfan.entry_point"] == "analytics_callback"
        assert root.attributes["everyfan.outcome"] == ("stale" if reset_before_run else "completed")
        assert len(ctx.recording) == (0 if reset_before_run else 6)
        assert ctx.errors == 0
    asyncio.run(go())


def test_stub_mode_never_auto_configures_azure(trace_case, monkeypatch):
    import backend.agents.workflow as workflow
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "must-not-use")

    def unexpected():
        raise AssertionError("Stub workflow tests must stay offline")

    monkeypatch.setattr(workflow, "configure", unexpected)
    runner = workflow.WorkflowRunner(SimpleNamespace(), AgentConfig(mode="stub"), tools=Tools(trace_case[0]))
    assert runner.telemetry.tracer is None
