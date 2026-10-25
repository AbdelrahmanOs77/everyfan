"""Bounded generation with identical stages in Framework and plain async runtimes."""

import asyncio
import importlib
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from shared.schemas import InsightBrief, Moment, Overlay

from .analyst import analyze
from .llm import create_model
from .names import NameAllowlist
from .producer import AirPlanItem, produce
from .templates import template_overlays
from .verifier import brief_from_moment, verify, verify_with_model
from .writers import WriterResult, write_one

log = logging.getLogger(__name__)


@dataclass
class Run:
    moment: Moment
    names: NameAllowlist
    plan: list[AirPlanItem]
    started: float
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    brief: InsightBrief | None = None
    drafts: dict[tuple[str, str], WriterResult] = field(default_factory=dict)
    approved: dict[tuple[str, str], Overlay] = field(default_factory=dict)
    attempts: dict[tuple[str, str], int] = field(default_factory=dict)
    reasons: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    repair: list[AirPlanItem] = field(default_factory=list)
    current: Callable[[], bool] = lambda: True


def item_key(item):
    return item.persona, item.language


class WorkflowRunner:
    def __init__(self, ctx, config, *, tools=None, fast=None, strong=None, framework=True):
        self.ctx, self.config, self.framework = ctx, config, framework
        if tools is None:
            from .mcp_server import EvidenceTools
            tools = EvidenceTools(getattr(ctx, "library", None))
        self.tools = tools
        self.fast = fast if fast is not None else create_model(config)
        self.strong = strong if strong is not None else create_model(config, "strong")
        self.cache = OrderedDict()
        self.history = {}

    def enqueue(self, container, doc):
        # A full queue or unavailable Cosmos must never stop the live stream.
        try:
            from backend.analytics.store import get_store
            store = get_store()
            if store is not None:
                store.enqueue(container, doc)
        except Exception:
            log.exception("Agent persistence unavailable")

    def audit(self, run, kind, **data):
        if not run.current():
            return
        self.enqueue("audit", {"match_id": run.moment.match_id, "moment_id": run.moment.moment_id,
                               "trace_id": run.trace_id, "kind": kind, **data})

    async def analyst(self, run):
        run.brief = await analyze(run.moment, self.tools, self.strong, self.ctx.budget,
                                  timeout_s=self.config.analyst_timeout_s)

    async def writers(self, run, repair=False):
        items = run.repair if repair else run.plan

        async def draft(item):
            key = item_key(item)
            run.attempts[key] = run.attempts.get(key, 0) + 1
            previous = run.drafts.get(key)
            result = await write_one(run.brief, run.moment, run.names, item, self.fast, self.ctx.budget,
                                     trace_id=run.trace_id, timeout_s=self.config.writer_timeout_s,
                                     repair_reason=run.reasons[key][-1] if repair else None,
                                     previous_draft=previous.draft.model_dump() if repair and previous.draft else None)
            run.drafts[key] = result
        await asyncio.gather(*(draft(item) for item in items))

    async def verifier(self, run):
        run.repair = []

        async def check(item):
            key = item_key(item)
            if key in run.approved:
                return
            result = run.drafts[key]
            reason = result.error
            if result.draft is not None:
                verdict = await verify_with_model(result.draft.model_dump(), run.brief, run.moment, run.names,
                                                  item.persona, model=self.strong, budget=self.ctx.budget,
                                                  timeout_s=self.config.verifier_timeout_s)
                reason = verdict.reason_code
                self.audit(run, "verdict", persona=item.persona, language=item.language,
                           attempt=run.attempts[key], **verdict.model_dump())
                if verdict.status == "approved":
                    run.approved[key] = result.draft.model_copy(update={"verification_status": "approved"})
                    return
            run.reasons.setdefault(key, []).append(reason or "SCHEMA")
            # Only a rejected draft gets a repair. Transport, budget and timeout errors fall back.
            if result.draft is not None and reason != "SCHEMA" and run.attempts[key] == 1:
                run.repair.append(item)
                self.audit(run, "repair", persona=item.persona, language=item.language, reason_code=reason)
        await asyncio.gather(*(check(item) for item in run.plan))

    async def plain(self, run):
        await self.analyst(run)
        await self.writers(run)
        await self.verifier(run)
        if run.repair:
            await self.writers(run, repair=True)
            await self.verifier(run)

    async def generate(self, run):
        if self.framework:
            try:
                graph = await asyncio.to_thread(importlib.import_module, "backend.agents.workflow_graph")
            except ImportError:
                log.info("Agent Framework unavailable; using plain async workflow")
            else:
                await graph.execute(self, run)
                return
        await self.plain(run)

    async def cached(self, run, item):
        key = run.moment.match_id, run.moment.moment_id, *item_key(item)
        candidates = [self.cache[key]] if key in self.cache else []
        demo = getattr(self.ctx, "demo", None)
        bundle = None
        library = getattr(self.ctx, "library", None)
        remaining = self.config.total_timeout_s - (time.monotonic() - run.started)
        if demo is not None and library is not None and remaining > 0:
            try:
                # DemoStore.get validates the simulation fingerprint, unlike direct bundle access.
                match = await asyncio.wait_for(library.get(run.moment.match_id), min(.1, remaining))
                bundle = demo.get(match)
            except Exception:
                log.info("Demo cache unavailable; using memory cache or templates")
        if bundle is not None and not bundle.stale:
            candidates.extend(bundle.overlays_for(run.moment.moment_id, item.persona, item.language))
        for candidate in candidates:
            try:
                overlay = Overlay.model_validate(candidate)
                # Cache approval is provenance, not a replacement for current evidence checks.
                data = overlay.model_dump()
                data["fields"] = {k: v for k, v in overlay.fields.items() if k not in {"attempts", "reason_codes"}}
                if (overlay.persona == item.persona and overlay.language == item.language
                        and overlay.source == "agent" and overlay.verification_status == "approved"
                        and overlay.prompt_version == f"writer_{item.persona}_v1"
                        and verify(data, brief_from_moment(run.moment), run.moment, run.names, item.persona).status == "approved"):
                    return overlay.model_copy(update={"fields": data["fields"]})
            except (ValueError, TypeError):
                continue
        return None

    async def run(self, moment, names, *, plan=None, started=None, current=lambda: True):
        started = time.monotonic() if started is None else started
        if not current():
            return []
        plan = produce(moment, self.history) if plan is None else plan
        run = Run(moment, names, plan, started, brief=brief_from_moment(moment), current=current)
        if not plan:
            return []
        reason = "OFF" if self.config.mode == "off" else "BUDGET"
        remaining = self.config.total_timeout_s - (time.monotonic() - started)
        producer_late = time.monotonic() - started > self.config.producer_timeout_s
        if producer_late:
            reason = "PRODUCER_TIMEOUT"
        if self.config.mode != "off" and not producer_late and self.ctx.budget.remaining() > 0:
            try:
                async with asyncio.timeout(max(0, remaining)):
                    await self.generate(run)
                reason = "REJECTED"
            except TimeoutError:
                reason = "DEADLINE"
            except Exception:
                log.exception("Agent workflow failed; using checked fallback")
                reason = "WORKFLOW_ERROR"
        if not current():
            return []
        self.enqueue("briefs", {"id": moment.moment_id, **run.brief.model_dump()})
        templates = {item_key(o): o for o in template_overlays(moment, names)}
        output = []
        for item in plan:
            if not current():
                break
            key = item_key(item)
            overlay = run.approved.get(key)
            reasons = run.reasons.get(key, []).copy()
            if overlay is None:
                overlay = await self.cached(run, item) if self.config.mode != "off" else None
                reasons.append("CACHE" if overlay is not None else reason)
                if overlay is None:
                    overlay = templates.get(key)
                    if overlay is None or verify(overlay.model_dump(), brief_from_moment(moment), moment, names, item.persona).status != "approved":
                        self.audit(run, "fallback_rejected", persona=item.persona, language=item.language)
                        continue  # fail closed even if a deterministic template is unexpectedly invalid
                self.audit(run, "fallback", persona=item.persona, language=item.language, reason_codes=reasons)
            if not current():
                break
            fields = {**overlay.fields, "generated_ms": round((time.monotonic() - started) * 1000),
                      "budget_ms": round(self.config.total_timeout_s * 1000),
                      "attempts": run.attempts.get(key, 0), "reason_codes": ",".join(reasons)}
            overlay = overlay.model_copy(update={"fields": fields, "trace_id": run.trace_id,
                                                 "slot": item.slot, "template_id": item.template_id,
                                                 "priority": item.priority, "ttl_s": item.ttl_s})
            if overlay.verification_status == "approved":
                cache_key = moment.match_id, moment.moment_id, *key
                self.cache[cache_key] = overlay.model_dump()
                self.cache.move_to_end(cache_key)
                while len(self.cache) > 512:
                    self.cache.popitem(last=False)
                self.enqueue("overlays", {"id": overlay.overlay_id, **overlay.model_dump()})
            await self.ctx.publish_overlay(overlay)
            output.append(overlay)
        return output

    async def aclose(self):
        for model in {self.fast, self.strong} - {None}:
            close = getattr(model, "aclose", None)
            if close:
                await close()
