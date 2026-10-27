"""The Analyst's evidence tools over the real MCP transport (Streamable HTTP).

    AGENT_TOOLS=mcp
    MCP_SERVER_URL=http://127.0.0.1:8000/mcp/     # the API's own mounted server (default), or a standalone one
    MCP_API_KEY=<same key as the server>

Same five method names and results as `EvidenceTools`, so the Analyst does not change. One MCP session
is kept open for the life of the API (stateless server, so a reconnect is always safe). If a call fails
the client reconnects once; the Analyst's deadline and fact-only fallback still bound everything.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import httpx

from .mcp_server import TOOL_NAMES

log = logging.getLogger(__name__)


class McpToolError(RuntimeError):
    pass


class McpEvidenceTools:
    def __init__(self, url: str, api_key: str = "", *, http_client_factory=None, timeout_s: float = 10.0):
        self.url, self.timeout_s = url, timeout_s
        self._headers = {"x-api-key": api_key} if api_key else {}
        self._factory = http_client_factory or (lambda headers: httpx.AsyncClient(headers=headers, timeout=timeout_s))
        self._session = None
        self._runner: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._stop: asyncio.Event | None = None
        self._lock = asyncio.Lock()
        self.calls = 0

    def __repr__(self) -> str:
        return f"McpEvidenceTools({self.url!r})"

    async def _serve(self) -> None:
        """Own the transport and session in one task, as anyio requires; others just use the session."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        try:
            async with self._factory(self._headers) as http:
                async with streamable_http_client(self.url, http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._session = session
                        self._ready.set_result(session)
                        await self._stop.wait()
        except Exception as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                log.warning("MCP evidence session closed: %s", type(exc).__name__)
        finally:
            self._session = None

    async def _connect(self):
        async with self._lock:
            if self._session is not None and self._runner is not None and not self._runner.done():
                return self._session
            self._stop, self._ready = asyncio.Event(), asyncio.get_running_loop().create_future()
            self._runner = asyncio.get_running_loop().create_task(self._serve())
            return await asyncio.wait_for(asyncio.shield(self._ready), self.timeout_s)

    async def _call(self, name: str, arguments: dict[str, Any]):
        arguments = {k: v for k, v in arguments.items() if v is not None}
        for attempt in (1, 2):
            try:
                session = await self._connect()
                result = await session.call_tool(name, arguments)
                break
            except McpToolError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                await self.aclose()  # stale session: reconnect once
        self.calls += 1
        if result.isError:
            text = " ".join(getattr(c, "text", "") for c in result.content)[:200]
            raise McpToolError(f"{name} failed: {text}")
        data = result.structuredContent
        if data is None:
            raise McpToolError(f"{name} returned no structured content")
        return data["result"] if name == "get_recent_events" and isinstance(data, dict) and "result" in data else data

    async def get_match_state(self, match_id, at_s):
        return await self._call("get_match_state", {"match_id": match_id, "at_s": at_s})

    async def get_recent_events(self, match_id, at_s, window_s, team_id=None):
        return await self._call("get_recent_events", {"match_id": match_id, "at_s": at_s, "window_s": window_s,
                                                      "team_id": team_id})

    async def get_player_statistics(self, match_id, player_id, at_s=None):
        return await self._call("get_player_statistics", {"match_id": match_id, "player_id": player_id, "at_s": at_s})

    async def get_moment_evidence(self, match_id, moment_id):
        return await self._call("get_moment_evidence", {"match_id": match_id, "moment_id": moment_id})

    async def compare_to_baseline(self, match_id, metric, window_s, at_s, team_id=None):
        return await self._call("compare_to_baseline", {"match_id": match_id, "metric": metric, "window_s": window_s,
                                                        "at_s": at_s, "team_id": team_id})

    async def list_tools(self) -> list[str]:
        session = await self._connect()
        return [t.name for t in (await session.list_tools()).tools]

    async def get_tactical_snapshot(self, match_id, at_s, window_s=60):
        return await self._call("get_tactical_snapshot", {"match_id": match_id, "at_s": at_s, "window_s": window_s})

    async def get_player_profile(self, match_id, player_id, at_s, window_s=300):
        return await self._call("get_player_profile", {"match_id": match_id, "player_id": player_id, "at_s": at_s, "window_s": window_s})

    async def aclose(self) -> None:
        runner, self._runner = self._runner, None
        if self._stop is not None:
            self._stop.set()
        if runner is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(runner, 5)
        self._session = None


assert set(TOOL_NAMES) <= set(dir(McpEvidenceTools))
