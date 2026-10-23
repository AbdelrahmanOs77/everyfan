import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.demo import DemoBundle, fingerprint
from backend.api.hub import Channel, ViewerClient, message
from backend.api.main import create_app
from backend.api.settings import ROOT, Settings
from backend.services.budget import DailyTokenBudget
from backend.simulator.generator import generate, load_scenario


def make_settings(tmp_path, **kw) -> Settings:
    s = Settings()
    s.transport = "local"
    s.data_dir = ROOT / "data"
    s.demo_dir = ROOT / "demo"
    s.broadcast_delay_s = 0.5
    s.allowed_speeds = [20.0, 600.0]
    s.admin_token = "admin-secret"
    s.frontend_origins = ["https://everyfan.example"]
    s.preload = []
    s.budget_file = tmp_path / "budget.json"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


def collect(ws, until, limit=20000):
    got = []
    for _ in range(limit):
        got.append(json.loads(ws.receive_text()))
        if until(got):
            break
    return got


def test_health_scenarios_and_arabic_metadata(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["transport"] == "local" and h["pipeline"]["errors"] == 0
    assert len(client.get("/api/scenarios").json()) == 4
    meta = client.get("/api/matches/match_001/metadata").json()
    assert meta["home"]["name_ar"] == "نادي النيل"
    assert all(p["name_ar"] for p in meta["home"]["players"])
    assert client.get("/api/matches/nope/metadata").status_code == 404


def test_cors_only_for_frontend_origin(client):
    ok = client.get("/api/health", headers={"Origin": "https://everyfan.example"})
    assert ok.headers["access-control-allow-origin"] == "https://everyfan.example"
    bad = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_event_lookup(client):
    goals = client.get("/api/matches/match_001/events", params={"types": "goal"}).json()
    assert [g["player_id"] for g in goals] == ["nil_09", "del_10", "del_09", "nil_10"]
    one = client.get(f"/api/matches/match_001/events/{goals[0]['event_id']}").json()
    assert one == goals[0]
    assert client.get("/api/matches/match_001/events/evt_99999").status_code == 404


def test_live_broadcast_delay_and_overlay_ordering(client):
    r = client.post("/api/matches/match_001/start", params={"speed": 600, "from_minute": 12})
    assert r.status_code == 200 and r.json()["control_token"]
    with client.websocket_connect("/ws/matches/match_001?persona=tactical&lang=en&tracking_hz=0") as ws:
        msgs = collect(ws, lambda g: any(m["type"] == "event" and m["data"]["type"] == "goal" for m in g))
    kinds = [m["type"] for m in msgs]
    goal_idx = next(i for i, m in enumerate(msgs) if m["type"] == "event" and m["data"]["type"] == "goal")
    overlay_idx = kinds.index("overlay")
    assert overlay_idx < goal_idx, "overlays must skip the broadcast delay and arrive before the delayed goal"
    overlays = [m for m in msgs if m["type"] == "overlay"]
    assert all(m["data"]["persona"] == "tactical" and m["data"]["language"] == "en" for m in overlays)
    assert "tracking" not in kinds


def test_control_token_locks_and_conflicts(client):
    r = client.post("/api/matches/match_001/start", params={"speed": 20})
    token = r.json()["control_token"]
    assert client.post("/api/matches/match_001/start", params={"speed": 20}).status_code == 409
    assert client.post("/api/matches/match_001/pause").status_code == 423
    assert client.post("/api/matches/match_001/pause", headers={"X-Control-Token": "wrong"}).status_code == 423
    r = client.post("/api/matches/match_001/pause", headers={"X-Control-Token": token})
    assert r.status_code == 200 and r.json()["state"] == "paused"
    r = client.post("/api/matches/match_001/speed", params={"value": 5}, headers={"X-Control-Token": token})
    assert r.status_code == 400  # 5x not in this deployment's allowed speeds
    r = client.post("/api/matches/match_001/seek", params={"minute": 60}, headers={"X-Admin-Token": "admin-secret"})
    assert r.status_code == 200
    assert client.post("/api/matches/match_001/stop", headers={"X-Control-Token": token}).status_code == 200


def test_start_rate_limit(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, start_per_minute=2))) as c:
        codes = [c.post("/api/matches/match_001/start", params={"speed": 20}).status_code for _ in range(3)]
        assert codes == [200, 409, 429]  # every attempt costs a token, even a refused one
        assert c.post("/api/matches/match_001/start", headers={"X-Admin-Token": "admin-secret"}).status_code == 200


def test_disallowed_speed_and_bad_minute(client):
    assert client.post("/api/matches/match_001/start", params={"speed": 1000}).status_code == 400
    assert client.post("/api/matches/match_001/start", params={"speed": 20, "from_minute": 95}).status_code == 400


def test_demo_playback_filters_and_seek(client):
    url = "/ws/demo/match_001?speed=60&from_minute=62&persona=tactical&lang=ar&tracking_hz=1"
    with client.websocket_connect(url) as ws:
        hello = json.loads(ws.receive_text())
        assert hello["type"] == "hello" and hello["data"]["mode"] == "demo"
        assert hello["data"]["bundle"]["counts"]["overlay"] == 24
        msgs = collect(ws, lambda g: any(m["type"] == "overlay" for m in g))
        ov = [m for m in msgs if m["type"] == "overlay"]
        assert ov[-1]["data"]["language"] == "ar" and ov[-1]["data"]["dir"] == "rtl"
        assert ov[-1]["data"]["show_at_s"] >= 62 * 60
        frames = [m["data"]["frame"] for m in msgs if m["type"] == "tracking"]
        assert frames and all(f % 2 == 0 for f in frames)  # 1 Hz requested
        ws.send_text(json.dumps({"action": "seek", "value": 30}))
        collect(ws, lambda g: g[-1]["type"] == "reset")          # seek starts a fresh run
        after = collect(ws, lambda g: g[-1]["type"] == "event")
        assert 1795 <= after[-1]["game_time_s"] < 1900           # playback resumed at 30'
        score = next(m for m in reversed(after) if m["type"] == "state")["data"]["score"]
        assert score == {"nile_fc": 1, "delta_utd": 0}            # state rebuilt for 30'


def test_websocket_connection_cap(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, max_ws_per_client=1))) as c:
        with c.websocket_connect("/ws/matches/match_001") as ws1:
            assert json.loads(ws1.receive_text())["type"] == "hello"
            with pytest.raises(WebSocketDisconnect) as exc:
                with c.websocket_connect("/ws/matches/match_001") as ws2:
                    ws2.receive_text()
            assert exc.value.code == 4429


async def test_daily_token_budget(tmp_path):
    b = DailyTokenBudget(1000, tmp_path / "b.json")
    assert await b.try_reserve(600)
    assert not await b.try_reserve(600)          # would exceed the cap
    await b.settle(600, 450)                      # real usage was lower
    assert b.status()["used"] == 450 and await b.try_reserve(500)
    again = DailyTokenBudget(1000, tmp_path / "b.json")
    assert again.used == 450                      # survives a restart
    assert not await DailyTokenBudget(0).try_reserve(1)  # cap 0 disables live AI


async def test_channel_delays_live_picture_but_not_overlays():
    ch = Channel("m", delay_s=0.3)
    c = ViewerClient("k")
    ch.add(c)
    ch.publish(message("event", "m", "r", 1.0, {"type": "pass"}))
    ch.publish(message("overlay", "m", "r", 1.0, {"persona": "beginner", "language": "en"}))
    first = json.loads(c.queue.get_nowait())
    assert first["type"] == "overlay" and c.queue.empty()
    t0 = time.monotonic()
    second = json.loads(await asyncio.wait_for(c.queue.get(), 2))
    assert second["type"] == "event" and time.monotonic() - t0 > 0.2


@pytest.mark.parametrize("path", sorted((ROOT / "demo").glob("*.bundle.json")), ids=lambda p: p.name)
def test_committed_demo_bundles_match_the_simulation(path: Path):
    bundle = DemoBundle.load(path)
    match = generate(load_scenario(bundle.scenario_id))
    assert bundle.fingerprint == fingerprint(match.events), "re-run: python -m backend.cli build-demo --all"
