"""Validated advanced-agent endpoints; demo mode never calls a model."""

import asyncio
from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from backend.analytics.api import _limit, get_match_evidence
from .ask import AskRequest, answer_question
from .config import AgentConfig
from .mcp_server import EvidenceTools

router = APIRouter(tags=["advanced agents"])


def recorded(request, ev):
    from backend.api.demo import fingerprint
    bundle = request.app.state.demo.bundles.get(ev.match_id)
    if not bundle or bundle.fingerprint != fingerprint(ev.events):
        return {}
    if not hasattr(bundle, "expanded_advanced"):
        from .advanced_demo import unpack
        bundle.expanded_advanced = unpack(bundle.advanced)
    return bundle.expanded_advanced


def context(request, live=False):
    plugin = getattr(request.app.state.ctx, "agents", None)
    cfg = plugin.config if plugin else AgentConfig()
    model = plugin.runner.strong or plugin.runner.fast if live and plugin else None
    fast = plugin.runner.fast if live and plugin else None
    return cfg, plugin, model, fast


def audit(plugin, kind, match_id, data):
    if plugin:
        plugin.runner.enqueue("audit", {"match_id": match_id, "kind": kind,
                                       "trace_id": data.get("trace_id"), "source": data.get("source"),
                                       "verification_status": data.get("verification_status")})
        plugin.runner.enqueue("briefs", {"id": data.get("answer_id", data.get("trace_id", kind)),
                                        "match_id": match_id, "facts": data.get("facts", {}), "kind": kind})


@router.post("/api/matches/{match_id}/ask")
async def ask_match(request: Request, match_id: str, body: AskRequest):
    from backend.services.ratelimit import RateLimiter
    cfg, plugin, model, fast = context(request, body.source == "live")
    if not hasattr(request.app.state, "ask_limiter"):
        request.app.state.ask_limiter = RateLimiter(cfg.ask_per_minute)
    key = request.client.host if request.client else "unknown"
    ok, retry = request.app.state.ask_limiter.allow(key)
    if not ok:
        raise HTTPException(429, "question rate limit exceeded", headers={"Retry-After": str(int(retry) + 1)})
    ev = await get_match_evidence(request, match_id)
    if body.source == "demo":
        for item in recorded(request, ev).get("questions", []):
            saved = item["request"]
            if all(saved.get(k) == getattr(body, k) for k in ("question", "at_s", "persona", "language", "player_id", "club_id")):
                return item["response"]
    tools = plugin.runner.tools if plugin else EvidenceTools(request.app.state.library)
    if isinstance(tools, EvidenceTools):
        tools._cache[match_id] = ev
    if body.source == "live":
        state = request.app.state.live.consumer.states.get(match_id)
        if state:
            body = body.model_copy(update={"at_s": min(body.at_s, int(state.game_time_s))})
    result = await answer_question(ev, body, tools, model=model, router_model=fast,
                                   budget=request.app.state.budget, config=cfg)
    audit(plugin, "ask", match_id, result)
    return result


@router.get("/api/matches/{match_id}/coach-notes")
async def notes(request: Request, match_id: str, until_s: float = Query(5400, ge=0, le=5400),
                persona: Literal["beginner", "tactical", "player", "club"] = "tactical",
                language: Literal["en", "ar"] = "en", source: Literal["demo", "live"] = "demo"):
    from .coach import coach_facts, coach_notes
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    cfg, plugin, model, _ = context(request, source == "live")
    if source == "demo":
        variants = recorded(request, ev).get("coach_notes", {})
        saved = variants.get(f"{persona}|{language}|")
        if saved is not None:
            return {"match_id": match_id, "at_s": until_s, "notes": [n for n in saved if n["game_clock_s"] <= until_s],
                    "definitions": {"coach": "Recorded checked tactical notes, filtered at the replay clock."}}
    elif plugin and persona == "tactical" and (match_id, language) in plugin.advanced_notes:
        return {"match_id": match_id, "at_s": until_s, "notes": [n for n in plugin.advanced_notes[match_id, language] if n["game_clock_s"] <= until_s],
                "definitions": {"coach": "Live checked tactical notes; no catch-up emission during seeks."}}
    await asyncio.to_thread(coach_facts, ev, cfg)
    if not hasattr(ev, "coach_text"):
        ev.coach_text = {}
    key = language, persona, source
    if key not in ev.coach_text:
        ev.coach_text[key] = []
    known_ids = {n["note_id"] for n in ev.coach_text[key]}
    pending = [n for n in ev.coach_facts if n["game_clock_s"] <= until_s and n["note_id"] not in known_ids]
    if pending:
        new = await coach_notes(ev, until_s, language, persona, model=model, budget=request.app.state.budget, config=cfg, exclude_ids=known_ids)
        ev.coach_text[key].extend(new)
        for note in new:
            audit(plugin, "coach", match_id, note)
    return {"match_id": match_id, "at_s": until_s, "notes": [n for n in ev.coach_text[key] if n["game_clock_s"] <= until_s],
            "definitions": {"coach": "Measured tactical changes, checked every 30 match-seconds with per-team, per-trigger cooldown; no coaching intentions inferred."}}


@router.get("/api/matches/{match_id}/report")
async def report(request: Request, match_id: str, phase: Literal["half", "full", "so_far"] = "so_far",
                 at_s: float = Query(5400, ge=0, le=5400), persona: Literal["beginner", "tactical", "player", "club"] = "beginner",
                 language: Literal["en", "ar"] = "en", club_id: str | None = None, source: Literal["demo", "live"] = "demo"):
    from .reports import match_report
    from .feature_writer import write_feature
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    cfg, plugin, model, _ = context(request, source == "live")
    # Availability must be checked even when a later viewer populated the cache.
    if persona != "club":
        club_id = None
    if phase == "half" and at_s < 2700 or phase == "full" and at_s < 5400:
        raise HTTPException(422, "report phase is not available at this clock")
    if source == "live" and plugin and persona == "beginner":
        saved = plugin.advanced_reports.get((match_id, phase, language))
        if saved:
            return saved
    if source == "demo" and phase != "so_far":
        saved = recorded(request, ev).get("reports", {}).get(f"{phase}|{persona}|{language}|{club_id or ''}")
        if saved:
            return saved
    if not hasattr(ev, "reports"):
        ev.reports = OrderedDict()
    key = phase, at_s if phase == "so_far" else 0, persona, language, club_id, source
    if key not in ev.reports:
        try:
            from backend.analytics.reference_pool import reference_pool
            reference = await reference_pool(request.app.state.library, match_id)
            bundle = request.app.state.demo.bundles.get(match_id)
            published = bundle.overlays() if source == "demo" and bundle else plugin.ctx.overlays(match_id)[1] if plugin else None
            result = await asyncio.to_thread(lambda: asyncio.run(match_report(ev, phase, at_s, persona, language, club_id, config=cfg, reference=reference, published_overlays=published)))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if model is not None:
            result.update(await write_feature(result["answer"], result["facts"], ev.meta, result["at_s"], model=model,
                                              budget=request.app.state.budget, config=cfg, persona=persona, language=language))
        ev.reports[key] = result
        while len(ev.reports) > 64:
            ev.reports.popitem(last=False)
        audit(plugin, "report", match_id, result)
    return ev.reports[key]
