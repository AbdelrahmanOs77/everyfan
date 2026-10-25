"""Five deterministic evidence tools: in-process, mounted MCP, or standalone HTTP."""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
from collections import OrderedDict
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field, JsonValue, validate_call
from starlette.responses import JSONResponse

from backend.analytics.evidence import MatchEvidence
from backend.api.library import MatchLibrary
from backend.api.settings import Settings

MatchID = Annotated[str, Field(pattern=r"^match_\d{3,}$", max_length=64, strict=True)]
MomentID = Annotated[str, Field(pattern=r"^mom_\d{3,}$", max_length=64, strict=True)]
EntityID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64, strict=True)]
Clock = Annotated[float, Field(ge=0, le=5400, allow_inf_nan=False, strict=True)]
Window = Annotated[float, Field(gt=0, le=5400, allow_inf_nan=False, strict=True)]
Metric = Literal["possession_pct", "pass_accuracy_pct", "ppda", "control_index", "shots", "passes",
                 "chaos_index", "turnovers_per_min", "passes_per_min"]
STRICT = ConfigDict(strict=True)
TOOL_NAMES = ("get_match_state", "get_recent_events", "get_player_statistics", "get_moment_evidence", "compare_to_baseline")


class EvidenceTools:
    """Thin, read-only wrappers over B's engine; cache builds without blocking the event loop."""

    def __init__(self, library=None, max_cached: int = 2):
        if max_cached < 1:
            raise ValueError("max_cached must be positive")
        self.library = library
        self.max_cached = max_cached
        self._cache: OrderedDict[str, MatchEvidence] = OrderedDict()
        self._lock = asyncio.Lock()

    async def _evidence(self, match_id: str) -> MatchEvidence:
        if self.library is None:
            self.library = MatchLibrary(Settings().data_dir, max_loaded=1)
        if not self.library.has(match_id):
            raise KeyError(f"Unknown match: {match_id}")
        async with self._lock:
            if match_id not in self._cache:
                match = await self.library.get(match_id)
                self._cache[match_id] = await asyncio.to_thread(MatchEvidence, match.metadata, match.events, match.frames)
                while len(self._cache) > self.max_cached:
                    self._cache.popitem(last=False)
            self._cache.move_to_end(match_id)
            return self._cache[match_id]

    @staticmethod
    def _team(evidence: MatchEvidence, team_id: str | None) -> None:
        if team_id is not None and team_id not in evidence.teams:
            raise ValueError(f"Unknown team: {team_id}")

    @validate_call(config=STRICT)
    async def get_match_state(self, match_id: MatchID, at_s: Clock) -> dict[str, JsonValue]:
        """Match state as known at at_s; never includes later match events."""
        evidence = await self._evidence(match_id)
        return deepcopy(await asyncio.to_thread(evidence.state_at, at_s))

    @validate_call(config=STRICT)
    async def get_recent_events(self, match_id: MatchID, at_s: Clock, window_s: Window,
                                team_id: EntityID | None = None) -> list[dict[str, JsonValue]]:
        """At most 50 recent events within (at_s - window_s, at_s], optionally for one team."""
        evidence = await self._evidence(match_id)
        self._team(evidence, team_id)
        return deepcopy(await asyncio.to_thread(evidence.recent_events, at_s, window_s, team_id, limit=50))

    @validate_call(config=STRICT)
    async def get_player_statistics(self, match_id: MatchID, player_id: EntityID, at_s: Clock | None = None) -> dict[str, JsonValue]:
        """Player statistics at at_s; omitted time explicitly means the complete match."""
        evidence = await self._evidence(match_id)
        result = await asyncio.to_thread(evidence.player_stats, player_id, at_s)
        if result is None:
            raise KeyError(f"Unknown player: {player_id}")
        return deepcopy(result)

    @validate_call(config=STRICT)
    async def get_moment_evidence(self, match_id: MatchID, moment_id: MomentID) -> dict[str, JsonValue]:
        """Verified moment facts, resolved event IDs, detection rule, and English/Arabic names."""
        evidence = await self._evidence(match_id)
        result = evidence.evidence(moment_id)
        if result is None:
            raise KeyError(f"Unknown moment: {moment_id}")
        return deepcopy(result)

    @validate_call(config=STRICT)
    async def compare_to_baseline(self, match_id: MatchID, metric: Metric, window_s: Window,
                                  at_s: Clock, team_id: EntityID | None = None) -> dict[str, JsonValue]:
        """Compare a metric over the recent window against its baseline up to at_s."""
        evidence = await self._evidence(match_id)
        self._team(evidence, team_id)
        return deepcopy(await asyncio.to_thread(evidence.baseline, metric, window_s, at_s, team_id))


class APIKeyMiddleware:
    """Protect every HTTP method before parsing MCP input. Lifespan passes through."""

    def __init__(self, app, api_key: str):
        self.app = app
        self._key = api_key.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._key:
            supplied = [value for name, value in scope.get("headers", []) if name.lower() == b"x-api-key"]
            if len(supplied) != 1 or not secrets.compare_digest(supplied[0], self._key):
                await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def mcp_asgi_app(library=None, *, api_key: str | None = None, path: str = "/", tools: EvidenceTools | None = None):
    """ASGI app with its own lifespan. For FastAPI mounting, use mount_mcp()."""
    tools = tools or EvidenceTools(library)
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "localhost,localhost:*,127.0.0.1,127.0.0.1:*,[::1],[::1]:*").split(",") if h.strip()]
    origins = [o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",") if o.strip()]
    server = FastMCP("EveryFan evidence", instructions="Read-only verified football evidence. Always pass the moment time when analysing live play.",
                     json_response=True, stateless_http=True, streamable_http_path=path,
                     transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                                   allowed_hosts=hosts, allowed_origins=origins))
    for name in TOOL_NAMES:
        server.add_tool(getattr(tools, name), structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                                                        idempotentHint=True, openWorldHint=False))
    child = server.streamable_http_app()
    child.add_middleware(APIKeyMiddleware, api_key=os.getenv("MCP_API_KEY", "") if api_key is None else api_key)
    child.state.evidence_tools = tools
    return child


def mount_mcp(app) -> None:
    """Mount at /mcp and start the SDK lifespan inside the existing API lifespan."""
    tools = EvidenceTools()
    child = mcp_asgi_app(tools=tools)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(parent):
        async with original_lifespan(parent):
            tools.library = parent.state.library
            async with child.router.lifespan_context(child):
                yield

    app.mount("/mcp", child)
    app.state.mcp_tools = tools
    app.router.lifespan_context = lifespan


def main() -> None:
    from pathlib import Path

    import uvicorn
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description="EveryFan read-only evidence MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(mcp_asgi_app(path="/mcp"), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
