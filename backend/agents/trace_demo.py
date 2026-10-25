"""Export local approval and failure traces without Azure or model calls."""

import argparse
import asyncio
import json
from pathlib import Path

from .config import AgentConfig
from .llm import StubModel
from .names import NameAllowlist
from .telemetry import Telemetry
from .workflow import WorkflowRunner


class RejectedWriter(StubModel):
    async def complete(self, system, user, json_schema=None):
        text, tokens = await super().complete(system, user, json_schema)
        data = json.loads(text)
        data["body"] = "999999"
        return json.dumps(data), tokens


async def export_trace(path: Path):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from backend.analytics.evidence import MatchEvidence
    from backend.api.hub import ViewerHub
    from backend.api.library import MatchLibrary
    from backend.api.plugins import PipelineContext
    from backend.api.settings import ROOT
    from backend.services.budget import DailyTokenBudget

    library = MatchLibrary(ROOT / "data")
    match = await library.get("match_001")
    evidence = MatchEvidence(match.metadata, match.events, match.frames)
    moment = next(m for m in evidence.moments if m.moment_id == "mom_044")
    provider, exporter = TracerProvider(), InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    ctx = PipelineContext(ViewerHub(0), DailyTokenBudget(500000), library=library)
    ctx.recording = []
    runner = WorkflowRunner(ctx, AgentConfig(mode="stub"),
                            telemetry=Telemetry(provider.get_tracer("everyfan.offline-proof")))
    try:
        names = NameAllowlist(match.metadata)
        await runner.run(moment, names, entry_point="offline_trace_proof")
        runner.fast = RejectedWriter()
        runner.cache.clear()
        await runner.run(moment, names, entry_point="offline_failure_proof")
        spans = exporter.get_finished_spans()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mode": "stub", "azure_exported": False,
                                   "spans": [json.loads(s.to_json()) for s in spans],
                                   "overlays": ctx.recording}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"traces": sum(s.name == "everyfan.workflow" for s in spans),
                "spans": len(spans), "overlays": len(ctx.recording)}
    finally:
        await runner.aclose()
        provider.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".venv/handoff/owner-c-phase6-traces.json"))
    print(json.dumps(asyncio.run(export_trace(parser.parse_args().out))))


if __name__ == "__main__":
    main()
