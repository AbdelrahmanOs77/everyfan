"""Read-only tools agree with Owner B, including over the real MCP transport."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from backend.agents.mcp_server import EvidenceTools, Metric, mcp_asgi_app
from backend.analytics.evidence import METRICS, MatchEvidence


@pytest.fixture(autouse=True)
def local_transport_hosts(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver,localhost:*,127.0.0.1:*")


class Library:
    def __init__(self, match):
        self.match = match
        self.loads = 0

    def has(self, match_id):
        return match_id == self.match.metadata.match_id

    async def get(self, match_id):
        if not self.has(match_id):
            raise KeyError(match_id)
        self.loads += 1
        return self.match


@pytest.fixture(scope="module")
def evidence(derby):
    return MatchEvidence(derby.metadata, derby.events, derby.frames)


def test_all_five_tools_match_owner_b_numbers_and_cache(derby, evidence):
    async def go():
        library = Library(derby)
        tools = EvidenceTools(library)
        assert set(get_args(Metric)) == set(METRICS)
        assert await tools.get_match_state("match_001", 3783) == evidence.state_at(3783)
        assert await tools.get_recent_events("match_001", 3783, 300) == evidence.recent_events(3783, 300, limit=50)
        assert await tools.get_recent_events("match_001", 3783, 300, "nile_fc") == evidence.recent_events(3783, 300, "nile_fc", limit=50)
        assert await tools.get_player_statistics("match_001", "nil_10", 3783) == evidence.player_stats("nil_10", 3783)
        assert await tools.get_player_statistics("match_001", "nil_10") == evidence.player_stats("nil_10")
        assert await tools.get_moment_evidence("match_001", "mom_044") == evidence.evidence("mom_044")
        for metric in METRICS:
            assert await tools.compare_to_baseline("match_001", metric, 300, 3900, "nile_fc") == evidence.baseline(metric, 300, 3900, "nile_fc")
        assert library.loads == 1
        recent = await tools.get_recent_events("match_001", 5400, 5400)
        assert len(recent) == 50 and all(e["game_clock_s"] <= 5400 for e in recent)
        # Evidence() returns nested references; callers must not corrupt the cache.
        first = await tools.get_moment_evidence("match_001", "mom_044")
        first["facts"]["shot_speed_kmh"] = 999
        assert (await tools.get_moment_evidence("match_001", "mom_044"))["facts"]["shot_speed_kmh"] == 104

    asyncio.run(go())


@pytest.mark.parametrize("method,args", [
    ("get_match_state", ("match_001", -1)),
    ("get_match_state", ("match_001", 5401)),
    ("get_match_state", ("match_001", float("nan"))),
    ("get_match_state", ("match_001", float("inf"))),
    ("get_match_state", ("match_001", True)),
    ("get_match_state", ("../../secret", 0)),
    ("get_recent_events", ("match_001", 100, 0)),
    ("get_recent_events", ("match_001", 100, 5401)),
    ("compare_to_baseline", ("match_001", "bogus", 300, 100)),
    ("get_moment_evidence", ("match_001", "bogus")),
])
def test_inputs_are_validated_before_loading_match(derby, method, args):
    async def go():
        library = Library(derby)
        with pytest.raises(ValueError):
            await getattr(EvidenceTools(library), method)(*args)
        assert library.loads == 0

    asyncio.run(go())


def test_unknown_match_moment_player_and_team(derby):
    async def go():
        tools = EvidenceTools(Library(derby))
        for method, args in [
            ("get_match_state", ("match_999", 0)),
            ("get_moment_evidence", ("match_001", "mom_999999")),
            ("get_player_statistics", ("match_001", "nobody", 10)),
            ("get_recent_events", ("match_001", 10, 10, "nobody")),
            ("compare_to_baseline", ("match_001", "ppda", 300, 10, "nobody")),
        ]:
            with pytest.raises((KeyError, ValueError)):
                await getattr(tools, method)(*args)

    asyncio.run(go())


def rpc(client, method, params=None, request_id=1, headers=None, path="/"):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return client.post(path, json=message, headers={"Accept": "application/json, text/event-stream", **(headers or {})})


@pytest.mark.parametrize("key", [None, "wrong-key", "é"])
def test_missing_and_incorrect_api_keys_return_401(derby, key):
    with TestClient(mcp_asgi_app(Library(derby), api_key="test-key")) as client:
        headers = {} if key is None else {"x-api-key": key.encode("utf-8")}
        response = rpc(client, "tools/list", headers=headers)
        assert response.status_code == 401
        assert "test-key" not in response.text


def test_tool_inventory_and_mcp_wire_call(derby, evidence):
    with TestClient(mcp_asgi_app(Library(derby), api_key="test-key")) as client:
        headers = {"x-api-key": "test-key"}
        response = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                             "clientInfo": {"name": "offline-test", "version": "1"}}, headers=headers)
        assert response.status_code == 200
        headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
        listed = rpc(client, "tools/list", headers=headers).json()["result"]["tools"]
        assert {t["name"] for t in listed} == {"get_match_state", "get_recent_events", "get_player_statistics", "get_moment_evidence", "compare_to_baseline"}
        assert all(t["annotations"]["readOnlyHint"] for t in listed)
        baseline = next(t for t in listed if t["name"] == "compare_to_baseline")
        assert set(baseline["inputSchema"]["properties"]["metric"]["enum"]) == set(METRICS)
        cases = [
            ("get_match_state", {"match_id": "match_001", "at_s": 3783}, evidence.state_at(3783)),
            ("get_recent_events", {"match_id": "match_001", "at_s": 3783, "window_s": 300}, {"result": evidence.recent_events(3783, 300, limit=50)}),
            ("get_player_statistics", {"match_id": "match_001", "player_id": "nil_10", "at_s": 3783}, evidence.player_stats("nil_10", 3783)),
            ("get_moment_evidence", {"match_id": "match_001", "moment_id": "mom_044"}, evidence.evidence("mom_044")),
            ("compare_to_baseline", {"match_id": "match_001", "metric": "ppda", "window_s": 300, "at_s": 3900, "team_id": "nile_fc"}, evidence.baseline("ppda", 300, 3900, "nile_fc")),
        ]
        for name, arguments, expected in cases:
            result = rpc(client, "tools/call", {"name": name, "arguments": arguments}, headers=headers).json()["result"]
            assert not result.get("isError")
            assert result["structuredContent"] == expected
        for invalid_time in (-1, True, "3783"):
            invalid = rpc(client, "tools/call", {"name": "get_match_state", "arguments": {"match_id": "match_001", "at_s": invalid_time}}, headers=headers).json()["result"]
            assert invalid["isError"]


def test_duplicate_keys_and_untrusted_host_or_origin_are_rejected(derby):
    with TestClient(mcp_asgi_app(Library(derby), api_key="test-key")) as client:
        response = client.post("/", content="not even json", headers=[("x-api-key", "test-key"), ("x-api-key", "test-key")])
        assert response.status_code == 401
        headers = {"x-api-key": "test-key", "Host": "attacker.example"}
        assert rpc(client, "tools/list", headers=headers).status_code == 421
        headers = {"x-api-key": "test-key", "Origin": "https://attacker.example"}
        assert rpc(client, "tools/list", headers=headers).status_code == 403


def test_unset_key_allows_local_access_and_cache_load_is_shared(derby, monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    library = Library(derby)
    with TestClient(mcp_asgi_app(library, api_key="")) as client:
        response = rpc(client, "tools/list")
        assert response.status_code == 200
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(rpc, client, "tools/call", {"name": "get_moment_evidence", "arguments": {"match_id": "match_001", "moment_id": "mom_044"}}, i) for i in range(3)]
            assert all(not f.result().json()["result"].get("isError") for f in futures)
        assert library.loads == 1


def test_mount_into_actual_api_initializes_mcp_lifespan(tmp_path, monkeypatch):
    from backend.api.main import create_app
    from tests.test_api import make_settings

    monkeypatch.setenv("MCP_API_KEY", "mount-key")
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/health").status_code == 200
        assert rpc(client, "tools/list", path="/mcp/").status_code == 401
        response = rpc(client, "tools/list", path="/mcp/", headers={"x-api-key": "mount-key"})
        assert response.status_code == 200
        assert len(response.json()["result"]["tools"]) == 5
        assert client.app.state.mcp_tools.library is client.app.state.library


def test_mcp_mount_failure_does_not_stop_api(tmp_path, monkeypatch):
    from backend.agents import mcp_server
    from backend.api.main import create_app
    from tests.test_api import make_settings

    def unavailable(_app):
        raise ImportError("optional MCP dependency unavailable")

    monkeypatch.setattr(mcp_server, "mount_mcp", unavailable)
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/mcp/").status_code == 404
