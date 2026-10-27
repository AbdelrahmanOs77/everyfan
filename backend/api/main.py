"""EveryFan backend API.

    uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

REST under /api (OpenAPI docs at /docs), WebSockets:
    /ws/matches/{match_id}   live broadcast (Event Hubs in Azure), broadcast delay applied
    /ws/demo/{match_id}      cached demo match, private playback per viewer, zero model cost
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.schemas import Overlay

from backend.services.budget import DailyTokenBudget
from backend.services.ratelimit import RateLimiter

from . import feed
from .demo import DemoPlayer, DemoStore
from .hub import ViewerClient, ViewerHub, message
from .library import MatchLibrary
from .live import LiveError, LiveService
from .plugins import PipelineContext, load_plugins
from .settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("everyfan.api")


def client_key(conn: Request | WebSocket) -> str:
    fwd = conn.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return conn.client.host if conn.client else "unknown"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started_at = time.time()
        library = MatchLibrary(settings.data_dir, settings.max_loaded_matches)
        hub = ViewerHub(settings.broadcast_delay_s)
        budget = DailyTokenBudget(settings.daily_token_cap, settings.budget_file)
        ctx = PipelineContext(hub, budget, settings, library)
        demo = DemoStore(settings.demo_dir)
        ctx.demo = demo
        load_plugins(ctx, settings.plugins)
        live = LiveService(settings, library, hub, ctx)
        limiters = {"start": RateLimiter(settings.start_per_minute),
                    "control": RateLimiter(settings.control_per_minute),
                    "read": RateLimiter(settings.read_per_minute)}
        for name, value in dict(settings=settings, library=library, hub=hub, budget=budget, ctx=ctx, demo=demo,
                                live=live, ws_counts={}, limiters=limiters).items():
            setattr(app.state, name, value)
        await live.start()
        for match_id in settings.preload:
            if library.has(match_id):
                asyncio.create_task(library.get(match_id))
        log.info("EveryFan API ready (transport=%s, delay=%ss, plugins=%s)", live.transport,
                 settings.broadcast_delay_s, ctx.loaded_plugins)
        yield
        await live.stop()

    app = FastAPI(title="EveryFan API", version=settings.version, lifespan=lifespan,
                  description="Synthetic football match intelligence: replay control, live and cached feeds.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.frontend_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Control-Token", "X-Admin-Token"], max_age=3600)
    # Register specific POSTs before the generic /{action} replay-control route.
    from backend.agents.feature_api import router as feature_router
    app.include_router(feature_router)

    # ------------------------------------------------------------- helpers

    def is_admin(request: Request | WebSocket) -> bool:
        token = request.headers.get("x-admin-token")
        return bool(settings.admin_token and token and secrets.compare_digest(token, settings.admin_token))

    def limit(request: Request, kind: str) -> None:
        if is_admin(request):
            return
        ok, retry = request.app.state.limiters[kind].allow(f"{kind}:{client_key(request)}")
        if not ok:
            raise HTTPException(429, "too many requests, slow down", headers={"Retry-After": str(int(retry) + 1)})

    def known(request: Request, match_id: str) -> None:
        if not request.app.state.library.has(match_id):
            raise HTTPException(404, f"unknown match {match_id}")

    @app.exception_handler(LiveError)
    async def live_error(_request: Request, exc: LiveError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    # ---------------------------------------------------------------- REST

    @app.get("/")
    async def root():
        return {"name": "EveryFan API", "docs": "/docs", "health": "/api/health", "scenarios": "/api/scenarios",
                "overlay_spec": "/api/spec/overlay", "mcp": "/mcp/"}

    @app.get("/api/health")
    async def health(request: Request):
        s = request.app.state
        last = s.live.consumer.last_message_at
        return {
            "status": "ok",
            "version": settings.version,
            "uptime_s": round(time.time() - s.started_at),
            "transport": s.live.transport,
            "transport_configured": settings.transport,
            "transport_fallback_reason": s.live.fallback_reason,
            "stream": {"messages_received": s.live.consumer.messages_received,
                       "last_message_s_ago": round(time.time() - last, 1) if last else None},
            "broadcast_delay_s": settings.broadcast_delay_s,
            "matches_loaded": s.library.loaded(),
            "live_replays_active": s.live.active_count(),
            "viewers": s.hub.viewer_count(),
            "pipeline": s.ctx.status(),
            "agents": s.ctx.agents.status() if getattr(s.ctx, "agents", None) else {"loaded": False},
            "mcp": {"mounted": hasattr(s, "mcp_tools"), "path": "/mcp/", "auth": "key" if os.getenv("MCP_API_KEY") else "none"},
            "budget": s.budget.status(),
            "demo_bundles": s.demo.catalog(),
        }

    @app.get("/api/scenarios")
    async def scenarios(request: Request):
        limit(request, "read")
        return request.app.state.library.catalog()

    @app.get("/api/matches/{match_id}/metadata")
    async def metadata(request: Request, match_id: str):
        limit(request, "read")
        known(request, match_id)
        m = await request.app.state.library.get(match_id)
        return m.metadata.model_dump(exclude_none=True)

    @app.get("/api/matches/{match_id}/state")
    async def state(request: Request, match_id: str):
        limit(request, "read")
        known(request, match_id)
        return {"replay": request.app.state.live.status(match_id), "state": request.app.state.live.state(match_id)}

    @app.get("/api/matches/{match_id}/replay")
    async def replay_status(request: Request, match_id: str):
        known(request, match_id)
        return request.app.state.live.status(match_id)

    @app.get("/api/matches/{match_id}/events")
    async def events(request: Request, match_id: str, from_s: float = 0, to_s: float = 5400,
                     types: str | None = None, limit_: int = Query(500, alias="limit", ge=1, le=2000)):
        limit(request, "read")
        known(request, match_id)
        wanted = set(types.split(",")) if types else None
        m = await request.app.state.library.get(match_id)
        out = [e.model_dump(exclude_none=True) for e in m.events
               if from_s <= e.game_time_s <= to_s and (wanted is None or e.type in wanted)]
        return out[:limit_]

    @app.get("/api/matches/{match_id}/events/{event_id}")
    async def event(request: Request, match_id: str, event_id: str):
        limit(request, "read")
        known(request, match_id)
        m = await request.app.state.library.get(match_id)
        try:
            seq = int(event_id.split("_")[1])
            e = m.events[seq - 1]
        except (IndexError, ValueError):
            raise HTTPException(404, "unknown event")
        if e.event_id != event_id:
            raise HTTPException(404, "unknown event")
        return e.model_dump(exclude_none=True)

    @app.post("/api/matches/{match_id}/start")
    async def start(request: Request, match_id: str, speed: float = 20, from_minute: float = 0):
        limit(request, "start")
        known(request, match_id)
        return await request.app.state.live.start_run(
            match_id, speed, from_minute, client_key(request), is_admin(request),
            request.headers.get("x-control-token"))

    @app.post("/api/matches/{match_id}/{action}")
    async def control(request: Request, match_id: str, action: str, value: float | None = None,
                      minute: float | None = None):
        if action not in ("pause", "resume", "stop", "speed", "seek"):
            raise HTTPException(404, "unknown action")
        limit(request, "control")
        known(request, match_id)
        return request.app.state.live.control(match_id, action, request.headers.get("x-control-token"),
                                              is_admin(request), minute if action == "seek" else value)

    @app.get("/api/budget")
    async def budget(request: Request):
        return request.app.state.budget.status()

    @app.get("/api/demo")
    async def demo_catalog(request: Request):
        return request.app.state.demo.catalog()

    @app.get("/api/spec/overlay")
    async def overlay_spec():
        return Overlay.model_json_schema()

    # ------------------------------------------- overlays feed, recap, Break it (Owners A + C)

    async def overlay_source(request: Request, match_id: str, source: str) -> tuple[str, str | None, list[dict], object]:
        """The live run's overlays, or the cached demo bundle's (auto: live when a live run has any)."""
        s = request.app.state
        run_id, live = s.ctx.overlays(match_id)
        if source == "live" or (source == "auto" and live):
            return "live", run_id, live, None
        bundle = s.demo.get(await s.library.get(match_id))
        return "demo", None, bundle.overlays(), bundle

    def wanted(o: dict, persona, lang, club, since, until) -> bool:
        return ((persona is None or o["persona"] == persona) and (lang is None or o["language"] == lang)
                and (club is None or o["persona"] != "club" or o.get("fields", {}).get("club_id") == club)
                and (since is None or o["show_at_s"] > since) and (until is None or o["show_at_s"] <= until))

    @app.get("/api/matches/{match_id}/overlays")
    async def overlays_feed(request: Request, match_id: str, persona: str | None = None, lang: str | None = None,
                            club: str | None = None, since: float | None = Query(None, ge=0, le=5400),
                            until: float | None = Query(None, ge=0, le=5400),
                            source: Literal["auto", "live", "demo"] = "auto",
                            limit_: int = Query(500, alias="limit", ge=1, le=5000)):
        """Public, machine-readable overlay feed (Contract C) for a rendering partner."""
        limit(request, "read")
        known(request, match_id)
        src, run_id, items, _ = await overlay_source(request, match_id, source)
        out = sorted((o for o in items if wanted(o, persona, lang, club, since, until)),
                     key=lambda o: (o["show_at_s"], o["priority"], o["overlay_id"]))[:limit_]
        return {"match_id": match_id, "source": src, "run_id": run_id, "count": len(out),
                "schema": "/api/spec/overlay", "overlays": out}

    @app.get("/api/matches/{match_id}/recap")
    async def recap(request: Request, match_id: str, persona: str = "beginner", lang: str = "en",
                    club: str | None = None, until_s: float = Query(5400, ge=0, le=5400),
                    source: Literal["auto", "live", "demo"] = "auto"):
        """End-of-match (or so-far) story built only from published, verified overlays."""
        known(request, match_id)
        s = request.app.state
        src, run_id, items, bundle = await overlay_source(request, match_id, source)
        match = await s.library.get(match_id)
        agents = getattr(s.ctx, "agents", None)
        final = until_s >= match.metadata.match_duration_s
        if src == "demo":
            limit(request, "read")
            stored = bundle.recaps.get(f"{persona}|{lang}|{club or ''}") if bundle is not None and final else None
            if stored:
                return stored
        # A model recap only for a finished live run; everything else is deterministic and free.
        use_model = bool(agents) and src == "live" and final and agents.config.mode != "off"
        limit(request, "control" if use_model else "read")
        try:
            if agents:
                result = await agents.recap(match.metadata, items, persona=persona, language=lang, club_id=club,
                                            until_s=until_s, cache_key=(src, run_id or (bundle.fingerprint if bundle else None)),
                                            use_model=use_model)
            else:
                from backend.agents.recap import deterministic_recap
                result = deterministic_recap(match.metadata, items, persona=persona, language=lang,
                                             club_id=club, until_s=until_s)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {**result.model_dump(), "feed_source": src, "run_id": run_id}

    @app.post("/api/demo/break-it")
    async def break_it(request: Request, match_id: str = "match_001", moment_id: str | None = None,
                       persona: str = "tactical", lang: str = "en", club: str | None = None):
        """Inject an invented number: the Verifier rejects it and the checked overlay replaces it."""
        limit(request, "control")
        known(request, match_id)
        from backend.agents.breakit import run_break_it
        try:
            return await run_break_it(match_id, moment_id, persona, lang, club, library=request.app.state.library)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except KeyError as exc:
            raise HTTPException(404, f"unknown moment {exc.args[0] if exc.args else ''}")

    # Owner B: evidence API (moments, evidence trail, stats at any second) for the UI and the MCP tools
    try:
        from backend.analytics.api import router as analytics_router
        app.include_router(analytics_router)
    except Exception:  # analytics must never stop the API from starting
        log.exception("evidence API not mounted")

    # Owner C: read-only MCP evidence tools, including the mounted SDK lifespan.
    try:
        from backend.agents.mcp_server import mount_mcp
        mount_mcp(app)
    except Exception:
        log.exception("MCP evidence server not mounted")

    # ----------------------------------------------------------- WebSockets

    async def _admit(ws: WebSocket) -> str | None:
        key = client_key(ws)
        counts: dict = ws.app.state.ws_counts
        total = sum(counts.values())
        if counts.get(key, 0) >= settings.max_ws_per_client or total >= settings.max_ws_total:
            await ws.close(code=4429, reason="too many connections")
            return None
        counts[key] = counts.get(key, 0) + 1
        return key

    def _release(ws: WebSocket, key: str) -> None:
        counts: dict = ws.app.state.ws_counts
        counts[key] = max(0, counts.get(key, 1) - 1)
        if not counts[key]:
            counts.pop(key, None)

    async def _pump(ws: WebSocket, client: ViewerClient) -> None:
        while True:
            text = await client.queue.get()
            await ws.send_text(text)
            if client.lagging:
                await ws.close(code=4408, reason="client too slow")
                return

    @app.websocket("/ws/matches/{match_id}")
    async def ws_live(ws: WebSocket, match_id: str, persona: str | None = None, lang: str | None = None,
                      tracking_hz: float = 2.0, club: str | None = None):
        if not ws.app.state.library.has(match_id):
            await ws.close(code=4404, reason="unknown match")
            return
        key = await _admit(ws)
        if key is None:
            return
        try:
            await ws.accept()
            client = ViewerClient(key, persona, lang, tracking_hz, club)
            ch = ws.app.state.hub.channel(match_id)
            hello = message("hello", match_id, None, 0.0, {
                "mode": "live", "broadcast_delay_s": settings.broadcast_delay_s,
                "replay": ws.app.state.live.status(match_id), "persona": persona, "language": lang, "club": club})
            await ws.send_text(json.dumps(hello, ensure_ascii=False))
            for m in ch.snapshot_messages():
                client.offer(json.dumps(m, ensure_ascii=False, separators=(",", ":")), m)
            ch.add(client)
            pump = asyncio.create_task(_pump(ws, client))
            try:
                while True:
                    await ws.receive_text()  # live viewers only send keep-alives
            except WebSocketDisconnect:
                pass
            finally:
                pump.cancel()
                ch.remove(client)
        finally:
            _release(ws, key)

    @app.websocket("/ws/demo/{match_id}")
    async def ws_demo(ws: WebSocket, match_id: str, persona: str | None = None, lang: str | None = None,
                      speed: float = 20.0, from_minute: float = 0.0, tracking_hz: float = 2.0,
                      club: str | None = None):
        if not ws.app.state.library.has(match_id):
            await ws.close(code=4404, reason="unknown match")
            return
        key = await _admit(ws)
        if key is None:
            return
        try:
            await ws.accept()
            match = await ws.app.state.library.get(match_id)
            bundle = ws.app.state.demo.get(match)
            client = ViewerClient(key, persona, lang, tracking_hz, club)

            def send(msg: dict) -> None:
                client.offer(json.dumps(msg, ensure_ascii=False, separators=(",", ":")), msg)

            speed = min(max(speed, 0.5), 60.0)
            start_s = min(max(from_minute, 0.0), 89.0) * 60
            await ws.send_text(json.dumps(message("hello", match_id, None, 0.0, {
                "mode": "demo", "broadcast_delay_s": 0, "persona": persona, "language": lang, "club": club,
                "bundle": {"counts": bundle.counts(), "plugins": bundle.plugins, "stale": bundle.stale},
                "controls": ["pause", "resume", "speed", "seek"]}), ensure_ascii=False))

            state = {"player": None, "task": None}

            def launch(at_s: float, spd: float) -> None:
                p = DemoPlayer(match, bundle, send, speed=spd, start_at_s=at_s, include_tracking=tracking_hz > 0)
                state["player"], state["task"] = p, asyncio.create_task(p.run())

            async def ticker() -> None:
                while True:
                    await asyncio.sleep(1)
                    p = state["player"]
                    if p:
                        send(feed.replay_msg(match_id, p.ctrl.status(), "demo"))

            launch(start_s, speed)
            pump = asyncio.create_task(_pump(ws, client))
            tick = asyncio.create_task(ticker())
            try:
                while True:
                    raw = await ws.receive_text()
                    try:
                        cmd = json.loads(raw)
                        action, value = cmd.get("action"), cmd.get("value", cmd.get("minute"))
                    except (ValueError, AttributeError):
                        continue
                    p = state["player"]
                    if p and p.ctrl.state in ("finished", "stopped") and action in ("seek", "resume", "restart"):
                        launch(float(value or 0) * 60 if action == "seek" else 0.0, p.ctrl.speed)
                    elif action == "restart":
                        p.stop()
                        launch(0.0, p.ctrl.speed)
                    elif p and action in ("pause", "resume", "speed", "seek"):
                        p.control(action, value)
            except WebSocketDisconnect:
                pass
            finally:
                for t in (pump, tick):
                    t.cancel()
                if state["player"]:
                    state["player"].stop()
        finally:
            _release(ws, key)

    return app


app = create_app()
