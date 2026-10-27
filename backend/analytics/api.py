"""Evidence API (Owner B). Read-only, deterministic, no model calls; mounted by backend/api/main.py.

    GET /api/analytics/config                                  formulas, weights, thresholds, rule text
    GET /api/analytics/status                                  live plugin + Cosmos DB writer status
    GET /api/matches/{id}/moments?until_s=&types=&min_importance=
    GET /api/matches/{id}/evidence/{moment_id}                 facts, rule, resolved evidence events, names
    GET /api/matches/{id}/stats?at_s=                          score, possession, PPDA, control, chaos, rhythm, momentum
    GET /api/matches/{id}/recent-events?at_s=&window_s=&team_id=&types=
    GET /api/matches/{id}/players/{player_id}/stats?at_s=      events, distance, top speed, badges
    GET /api/matches/{id}/baseline?metric=&window_s=&at_s=&team_id=
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Query, Request

from .config import load_config
from .evidence import METRICS, MatchEvidence
from .moments import rule_descriptions

router = APIRouter(tags=["analytics (Owner B)"])

_cache: OrderedDict[str, MatchEvidence] = OrderedDict()
_lock = asyncio.Lock()
MAX_CACHED = 4


def _limit(request: Request) -> None:
    limiters = getattr(request.app.state, "limiters", None)
    if not limiters:
        return
    fwd = request.headers.get("x-forwarded-for")
    key = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    ok, retry = limiters["read"].allow(f"read:{key}")
    if not ok:
        raise HTTPException(429, "too many requests, slow down", headers={"Retry-After": str(int(retry) + 1)})


async def get_match_evidence(request: Request, match_id: str) -> MatchEvidence:
    library = request.app.state.library
    if not library.has(match_id):
        raise HTTPException(404, f"unknown match {match_id}")
    async with _lock:
        if match_id in _cache:
            _cache.move_to_end(match_id)
            return _cache[match_id]
        match = await library.get(match_id)
        ev = await asyncio.to_thread(MatchEvidence, match.metadata, match.events, match.frames)
        _cache[match_id] = ev
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
        return ev


@router.get("/api/analytics/config")
async def analytics_config():
    cfg = load_config()
    return {"config": cfg, "rules": rule_descriptions(cfg)}


@router.get("/api/matches/{match_id}/tactics")
async def tactics_snapshot(request: Request, match_id: str, at_s: float = Query(5400, ge=0, le=5400),
                           window_s: float = Query(60, gt=0, le=5400), team_id: str | None = None,
                           include_space: bool = True):
    from .live_tactics import tactical_snapshot
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    if team_id is not None and team_id not in ev.teams:
        raise HTTPException(404, "unknown team")
    return await asyncio.to_thread(tactical_snapshot, ev, at_s, window_s, team_id, include_space)


@router.get("/api/matches/{match_id}/players/{player_id}/profile")
async def profile_snapshot(request: Request, match_id: str, player_id: str,
                           at_s: float = Query(5400, ge=0, le=5400),
                           window_s: float = Query(300, gt=0, le=5400), sections: str | None = None):
    from .player_profile import player_profile
    from .reference_pool import reference_pool
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    if player_id not in ev.players:
        raise HTTPException(404, "unknown player")
    selected = sections.split(",") if sections else None
    reference = await reference_pool(request.app.state.library, match_id) if selected is None or set(selected) & {"benchmark", "progress", "role_index"} else ()
    try:
        return await asyncio.to_thread(player_profile, ev, player_id, at_s, window_s, reference, selected)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/api/analytics/status")
async def analytics_status(request: Request):
    ctx = getattr(request.app.state, "ctx", None)
    plugin = getattr(ctx, "analytics", None)
    return plugin.status() if plugin else {"plugin_loaded": False,
                                            "hint": "add backend.analytics.plugin:register to PIPELINE_PLUGINS"}


@router.get("/api/matches/{match_id}/moments")
async def moments(request: Request, match_id: str, until_s: float | None = None, types: str | None = None,
                  min_importance: float = Query(0.0, ge=0.0, le=1.0)):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    return ev.list_moments(until_s, set(types.split(",")) if types else None, min_importance)


@router.get("/api/matches/{match_id}/evidence/{moment_id}")
async def evidence(request: Request, match_id: str, moment_id: str):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    out = ev.evidence(moment_id)
    if out is None:
        raise HTTPException(404, f"unknown moment {moment_id}")
    return out


@router.get("/api/matches/{match_id}/stats")
async def stats(request: Request, match_id: str, at_s: float | None = Query(None, ge=0, le=5400)):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    return await asyncio.to_thread(ev.state_at, at_s)


@router.get("/api/matches/{match_id}/recent-events")
async def recent_events(request: Request, match_id: str, at_s: float | None = Query(None, ge=0, le=5400),
                        window_s: float = Query(60, gt=0, le=5400), team_id: str | None = None,
                        types: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    return ev.recent_events(at_s, window_s, team_id, set(types.split(",")) if types else None, limit)


@router.get("/api/matches/{match_id}/advanced-stats")
async def advanced_match_stats(request: Request, match_id: str,
                               at_s: float = Query(5400, ge=0, le=5400),
                               window_s: float = Query(300, gt=0, le=5400)):
    """Rolling and match-to-date team analysis, passing networks and event maps."""
    from .advanced import advanced_stats

    _limit(request)
    ev = await get_match_evidence(request, match_id)
    return await asyncio.to_thread(advanced_stats, ev.meta, ev.events, at_s=at_s, window_s=window_s,
                                   cfg=ev.cfg, tracking_index=ev.tracking)


@router.get("/api/matches/{match_id}/players/{player_id}/stats")
async def player_stats(request: Request, match_id: str, player_id: str,
                       at_s: float | None = Query(None, ge=0, le=5400)):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    out = await asyncio.to_thread(ev.player_stats, player_id, at_s)
    if out is None:
        raise HTTPException(404, f"unknown player {player_id}")
    return out


@router.get("/api/matches/{match_id}/fan-stats")
async def fan_match_stats(request: Request, match_id: str,
                          at_s: float = Query(5400, ge=0, le=5400),
                          window_s: float = Query(300, gt=0, le=5400)):
    """Tracking positions, leaderboards, club summaries and source-backed momentum."""
    from .fan_extras import fan_stats

    _limit(request)
    ev = await get_match_evidence(request, match_id)
    return await asyncio.to_thread(fan_stats, ev, at_s=at_s, window_s=window_s)


@router.get("/api/matches/{match_id}/players/{player_id}/tracking-samples")
async def tracking_samples(request: Request, match_id: str, player_id: str,
                            at_s: float = Query(5400, ge=0, le=5400),
                            window_s: float = Query(5400, gt=0, le=5400),
                            offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    """Original source positions, paginated within a bounded as-of time window."""
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    out = ev.tracking_samples(player_id, at_s, window_s, offset, limit)
    if out is None:
        raise HTTPException(404, f"unknown player {player_id}")
    return out


@router.get("/api/matches/{match_id}/baseline")
async def baseline(request: Request, match_id: str, metric: str = Query(..., description=", ".join(METRICS)),
                   window_s: float = Query(300, gt=0, le=5400), at_s: float | None = Query(None, ge=0, le=5400),
                   team_id: str | None = None):
    _limit(request)
    ev = await get_match_evidence(request, match_id)
    try:
        return await asyncio.to_thread(ev.baseline, metric, window_s, at_s, team_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
