"""Owner B: metrics, moments, determinism, live plugin, evidence API, Cosmos writer."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shared.schemas import Moment
from backend.analytics import MatchAnalytics
from backend.analytics.evidence import MatchEvidence
from backend.analytics.store import CosmosStore
from backend.services.consumer import MatchStateConsumer
from backend.services.stream.local import LocalBus
from backend.simulator.generator import generate, list_scenarios, load_scenario
from backend.simulator.replay import ReplayController

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def evidence(matches):
    return {sid: MatchEvidence(m.metadata, m.events, m.frames) for sid, m in matches.items()}


def _dump(moments) -> str:
    return json.dumps([m.model_dump(mode="json") for m in moments], sort_keys=True)


# ------------------------------------------------------------- determinism


def test_same_seed_gives_identical_metrics_and_moments(derby, evidence):
    """Acceptance test (plan 6.3): byte-identical stats and moments across runs of the same seed."""
    again = generate(load_scenario("derby_balanced"))
    ev2 = MatchEvidence(again.metadata, again.events, again.frames)
    first = evidence["derby_balanced"]
    assert _dump(ev2.moments) == _dump(first.moments)
    for t in (600, 2700, 3783, 5400):
        assert json.dumps(ev2.state_at(t), sort_keys=True) == json.dumps(first.state_at(t), sort_keys=True)


@pytest.mark.parametrize("scenario_id", list_scenarios())
def test_moments_match_golden_file(evidence, scenario_id):
    ev = evidence[scenario_id]
    got = [[m.moment_id, m.game_clock_s, m.type, m.rule_id, m.team_id] for m in ev.moments
           if m.type != "player_milestone"]
    path = GOLDEN / f"{ev.match_id}.moments.json"
    assert path.exists(), "create it: python -m backend.analytics golden"
    assert got == json.loads(path.read_text()), "rules or config changed: review, then python -m backend.analytics golden"


# ----------------------------------------------------------------- metrics


@pytest.mark.parametrize("window,possession,ppda", [((18, 36), 38, 5.3), ((54, 67), 70, 1.7), ((80, 90), 45, 2.2)])
def test_metrics_reproduce_owner_a_measured_windows(derby, window, possession, ppda):
    a = MatchAnalytics(derby.metadata)
    for e in derby.events:
        a.add(e)
    start, end = window
    w, at = (end - start) * 60, end * 60
    assert round(100 * a.possession_share("nile_fc", w, at)) == pytest.approx(possession, abs=1)
    assert a.ppda("nile_fc", w, at) == pytest.approx(ppda, abs=0.1)


def test_ball_speed_and_pass_metrics(derby):
    a = MatchAnalytics(derby.metadata)
    for e in derby.events:
        a.add(e)
    rocket = max(a.shot_info.values(), key=lambda s: s["speed_kmh"] or 0)
    assert 100 < rocket["speed_kmh"] < 140
    assert all(0 <= p["difficulty"] <= 1 for p in a.pass_info.values())
    acc = a.pass_accuracy("nile_fc", None)
    assert acc == pytest.approx(0.836, abs=0.001)  # summary.json: 587 passes, 83.6%


# ----------------------------------------------------------------- moments


def test_demo_match_story_is_detected(evidence):
    ms = evidence["derby_balanced"].moments
    goals = [m for m in ms if m.type == "goal"]
    assert [m.game_clock_s for m in goals] == [726, 1864, 2942, 3783]
    rocket_goal = goals[-1]
    assert rocket_goal.verified_facts["scorer_id"] == "nil_10"
    assert rocket_goal.verified_facts["shot_speed_kmh"] >= 100
    assert (rocket_goal.verified_facts["home_score"], rocket_goal.verified_facts["away_score"]) == (2, 2)

    def any_in(mtype, team, lo, hi):
        return any(m.type == mtype and m.team_id == team and lo * 60 <= m.game_clock_s <= hi * 60 for m in ms)

    assert any_in("pressing_shift", "nile_fc", 54, 67), "Nile's high press (54-67') must be found"
    assert any_in("pressing_shift", "delta_utd", 18, 36), "Delta take control (18-36')"
    assert any_in("momentum_shift", "delta_utd", 16, 36)
    assert any(m.type == "big_chance" and m.team_id == "delta_utd" and m.game_clock_s == 5167 for m in ms)
    assert any(m.type == "control_to_chaos" and m.game_clock_s >= 80 * 60 for m in ms)
    assert any(m.type == "player_milestone" and m.verified_facts.get("badge") == "rocket" for m in ms)


def test_red_card_moment(evidence):
    red = [m for m in evidence["red_card_60"].moments if m.type == "red_card"]
    assert len(red) == 1 and red[0].player_id == "nil_04" and red[0].verified_facts["players_left"] == 10


@pytest.mark.parametrize("scenario_id", list_scenarios())
def test_every_moment_is_valid_and_its_evidence_resolves(evidence, scenario_id):
    ev = evidence[scenario_id]
    ids = [m.moment_id for m in ev.moments]
    assert len(ids) == len(set(ids))
    cooldown = 90
    last = {}
    for m in ev.moments:
        Moment.model_validate(m.model_dump())
        assert m.evidence_event_ids and all(eid in ev.event_by_id for eid in m.evidence_event_ids)
        assert all(ev.event_by_id[eid].game_clock_s <= m.game_clock_s for eid in m.evidence_event_ids)
        assert all(v is not None for v in m.verified_facts.values())
        if m.type not in ("goal", "red_card", "player_milestone"):
            assert m.game_clock_s - last.get(m.type, -cooldown) >= cooldown
            last[m.type] = m.game_clock_s
    agent_moments = [m for m in ev.moments if m.importance >= 0.5]
    assert 5 <= len(agent_moments) <= 60  # enough to tell the story, few enough for the agents


# ------------------------------------------------------- live plugin + seek


class FakeLibrary:
    def __init__(self, match):
        self.match = match

    async def get(self, _match_id):
        return self.match


class FakeCtx:
    def __init__(self, match):
        self.library = FakeLibrary(match)
        self.published: list[Moment] = []
        self.event_handlers, self.tracking_handlers, self.reset_handlers, self.control_handlers = [], [], [], []

    def on_event(self, fn): self.event_handlers.append(fn); return fn
    def on_tracking(self, fn): self.tracking_handlers.append(fn); return fn
    def on_reset(self, fn): self.reset_handlers.append(fn); return fn
    def on_control(self, fn): self.control_handlers.append(fn); return fn
    def spawn(self, coro): return asyncio.get_running_loop().create_task(coro)

    async def publish_moment(self, m):
        self.published.append(Moment.model_validate(m))


async def _run_plugin(match, start_at_s: float = 0.0) -> list[Moment]:
    from backend.analytics.plugin import register

    ctx = FakeCtx(match)
    register(ctx)

    async def call(handlers, *args):
        for fn in handlers:
            r = fn(*args)
            if asyncio.iscoroutine(r):
                await r

    bus = LocalBus()
    sub = bus.subscribe()
    consumer = MatchStateConsumer(on_reset=lambda s: call(ctx.reset_handlers, s),
                                  on_event=lambda e, s: call(ctx.event_handlers, e, s),
                                  on_tracking=lambda f, s: call(ctx.tracking_handlers, f, s),
                                  on_control=lambda c, s: call(ctx.control_handlers, c, s))
    task = asyncio.create_task(consumer.consume(sub, stop_when_finished=True))
    ctrl = ReplayController(match.metadata, match.events, match.frames, bus.publisher(), speed=0,
                            start_at_s=start_at_s)
    await ctrl.run()
    await task
    return ctx.published


def test_live_plugin_publishes_exactly_the_evidence_moments(derby, evidence):
    published = asyncio.run(_run_plugin(derby))
    assert _dump(published) == _dump(evidence["derby_balanced"].moments_in_publish_order())


def test_seek_keeps_moment_ids_and_does_not_replay_history(derby, evidence):
    seek = 60 * 60
    published = asyncio.run(_run_plugin(derby, start_at_s=seek))
    full = [m for m in evidence["derby_balanced"].moments_in_publish_order() if m.game_clock_s >= seek]
    assert published and all(m.game_clock_s >= seek - 1 for m in published)
    # Same IDs and facts as a full run (distance badges included, thanks to the tracking back-fill).
    assert [m.moment_id for m in published] == [m.moment_id for m in full]
    assert _dump(published) == _dump(full)


# ------------------------------------------------------------ evidence API


@pytest.fixture
def api(tmp_path):
    from backend.api.main import create_app
    from tests.test_api import make_settings

    settings = make_settings(tmp_path, plugins=["backend.analytics.plugin:register"])
    with TestClient(create_app(settings)) as c:
        yield c


def test_evidence_api(api):
    moments = api.get("/api/matches/match_001/moments?types=goal").json()
    assert [m["game_clock_s"] for m in moments] == [726, 1864, 2942, 3783]
    goal = moments[-1]
    ev = api.get(f"/api/matches/match_001/evidence/{goal['moment_id']}").json()
    assert ev["all_evidence_resolved"] and ev["rule"]["rule_id"] == "GOAL_V1"
    assert ev["names"]["nil_10"]["name_ar"]
    assert api.get("/api/matches/match_001/evidence/mom_999999").status_code == 404

    state = api.get("/api/matches/match_001/stats?at_s=3700").json()
    assert state["score"] == {"nile_fc": 1, "delta_utd": 2}  # before the 63:03 equaliser
    assert state["teams"]["nile_fc"]["ppda_last_5"] is not None

    p = api.get("/api/matches/match_001/players/nil_10/stats?at_s=3800").json()
    assert p["events"]["goals"] == 1 and p["distance_km"] > 5 and p["top_speed_kmh"] > 20
    assert api.get("/api/matches/match_001/players/nobody/stats").status_code == 404

    b = api.get("/api/matches/match_001/baseline?metric=ppda&at_s=3900&team_id=nile_fc").json()
    assert b["rows"][0]["current"] < b["rows"][0]["match_baseline"]  # Nile pressing harder than usual
    assert api.get("/api/matches/match_001/baseline?metric=nonsense").status_code == 422

    recent = api.get("/api/matches/match_001/recent-events?at_s=3790&window_s=30&types=goal").json()
    assert [e["event_id"] for e in recent] == [goal["evidence_event_ids"][-1]]
    assert api.get("/api/analytics/config").json()["rules"]["PRESS_SHIFT_V1"]
    status = api.get("/api/analytics/status").json()
    assert status["cosmos"] == {"enabled": False}
    assert api.get("/api/matches/nope/moments").status_code == 404
    assert api.get("/api/health").json()["pipeline"]["errors"] == 0


# ---------------------------------------------------------------- Cosmos DB


class FakeContainer:
    def __init__(self):
        self.items = {}

    async def upsert_item(self, doc):
        json.dumps(doc)  # must be JSON-serialisable
        self.items[doc["id"]] = doc


class FakeDb:
    def __init__(self):
        self.containers = {}

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeContainer())


class FakeClient:
    def __init__(self):
        self.db = FakeDb()

    def get_database_client(self, _name):
        return self.db

    async def close(self):
        pass


def test_cosmos_store_upserts_idempotently(derby, evidence, monkeypatch):
    store = CosmosStore("https://fake.documents.azure.com:443/", "everyfan", key="k")
    client = FakeClient()
    monkeypatch.setattr(store, "_client", lambda: (client, None))

    async def go():
        for e in derby.events[:50]:
            store.add_event(e, "run_a")
        for e in derby.events[:50]:  # a second run: already written, skipped
            store.add_event(e, "run_b")
        for m in evidence["derby_balanced"].moments[:5]:
            store.add_moment(m, "run_a")
        store.audit("match_001", "test", {"ok": True})
        await store.flush()

    asyncio.run(go())
    c = client.db.containers
    assert len(c["events"].items) == 50 and len(c["moments"].items) == 5 and len(c["audit"].items) == 1
    assert all(d["match_id"] == "match_001" for d in c["events"].items.values())
    assert store.status()["written"] == 56 and store.status()["failed"] == 0
    with pytest.raises(ValueError):
        store.enqueue("nope", {"match_id": "x"})


def test_store_is_off_without_endpoint(monkeypatch):
    import backend.analytics.store as st

    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.setattr(st, "_checked", False)
    monkeypatch.setattr(st, "_store", None)
    assert st.get_store() is None
