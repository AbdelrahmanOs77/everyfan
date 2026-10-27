"""Integration of Owners A, B and C: club persona, recap, overlay feed, Break it, MCP client,
cross-tenant Foundry auth, evals and deployment config. Offline: no Azure, no real model."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.agents.names import NameAllowlist
from backend.agents.producer import produce
from backend.agents.recap import RecapText, build_recap, deterministic_recap, verify_recap
from backend.agents.templates import club_overlays, template_for
from backend.agents.verifier import brief_from_moment, verify
from backend.analytics.evidence import MatchEvidence
from backend.api.demo import DemoBundle
from backend.api.hub import ViewerClient
from backend.api.main import create_app
from backend.api.settings import ROOT
from shared.schemas import Overlay
from tests.test_agents_templates import ROWS, eval_moment
from tests.test_api import collect, make_settings

PLUGINS = ["backend.analytics.plugin:register", "backend.agents.plugin:register"]


@pytest.fixture(scope="module")
def names_by_match(matches):
    return {m.metadata.match_id: NameAllowlist(m.metadata) for m in matches.values()}


@pytest.fixture(scope="module")
def derby_moments(derby):
    return MatchEvidence(derby.metadata, derby.events, derby.frames).moments


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, plugins=PLUGINS))) as c:
        yield c


# --------------------------------------------------------------------------- Favorite Club persona

@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['match_id']}-{r['moment_id']}")
def test_club_overlays_for_both_clubs_are_verified(row, names_by_match):
    moment = eval_moment(row)
    names = names_by_match[moment.match_id]
    overlays = club_overlays(moment, names)
    if moment.team_id is None:
        assert overlays == []  # match-level moments have no side to support
        return
    assert {(o.fields["club_id"], o.language) for o in overlays} == {(t, lang) for t in names.teams for lang in ("en", "ar")}
    assert len({o.overlay_id for o in overlays}) == 4
    for o in overlays:
        assert verify(o.model_dump(), brief_from_moment(moment), moment, names, "club").status == "approved"
        club = names.teams[o.fields["club_id"]]
        assert (club.name_ar if o.language == "ar" else club.name) in o.headline + o.body
        assert o.dir == ("rtl" if o.language == "ar" else "ltr") and o.persona == "club"


def test_every_club_overlay_of_every_match_is_verified(matches):
    for match in matches.values():
        names = NameAllowlist(match.metadata)
        for moment in MatchEvidence(match.metadata, match.events, match.frames).moments:
            for o in club_overlays(moment, names):
                verdict = verify(o.model_dump(), brief_from_moment(moment), moment, names, "club")
                assert verdict.status == "approved", (moment.moment_id, o.overlay_id, verdict)


def test_club_partisan_framing_and_respect_checks(derby, derby_moments):
    names = NameAllowlist(derby.metadata)
    goal = next(m for m in derby_moments if m.type == "goal" and m.team_id == "nile_fc")
    ours = template_for(goal, names, "club", "en", "nile_fc")
    theirs = template_for(goal, names, "club", "en", "delta_utd")
    assert ours.headline.startswith("Goal for Nile FC") and "Delta United" in theirs.headline
    brief = brief_from_moment(goal)
    for text, lang in (("Delta United are pathetic. Score 1-0.", "en"), ("دلتا يونايتد فريق فاشل.", "ar")):
        base = template_for(goal, names, "club", lang, "nile_fc")
        bad = {**base.model_dump(), "body": text}
        assert verify(bad, brief, goal, names, "club").reason_code == "TONE"
    no_club = {**theirs.model_dump(), "headline": "A goal", "body": "Ramy Galal scores in minute 13."}
    assert verify(no_club, brief, goal, names, "club").reason_code == "TONE"
    wrong = {**ours.model_dump(), "fields": {**ours.fields, "club_id": "real_madrid"}}
    assert verify(wrong, brief, goal, names, "club").reason_code == "SCHEMA"


def test_producer_plans_club_items_per_club_and_cooldown(derby, derby_moments):
    clubs = ("nile_fc", "delta_utd")
    goal = next(m for m in derby_moments if m.type == "goal")
    items = produce(goal, {}, clubs)
    club_items = [i for i in items if i.persona == "club"]
    assert {(i.club_id, i.language) for i in club_items} == {(c, lang) for c in clubs for lang in ("en", "ar")}
    assert produce(goal, {}) and not [i for i in produce(goal, {}) if i.persona == "club"]  # opt-in
    chaos = next(m for m in derby_moments if m.type == "control_to_chaos")
    assert not [i for i in produce(chaos, {}, clubs) if i.persona == "club"]
    history = {}
    press = [m for m in derby_moments if m.type in ("pressing_shift", "momentum_shift") and m.team_id]
    produce(press[0], history, clubs)
    later = press[0].model_copy(update={"game_clock_s": press[0].game_clock_s + 10, "moment_id": "mom_9998"})
    assert not [i for i in produce(later, history, clubs) if i.persona == "club"]  # 45 s cooldown applies


def test_viewer_club_filter():
    nile = {"type": "overlay", "data": {"persona": "club", "language": "en", "fields": {"club_id": "nile_fc"}}}
    delta = {"type": "overlay", "data": {"persona": "club", "language": "en", "fields": {"club_id": "delta_utd"}}}
    viewer = ViewerClient("k", "club", "en", club="nile_fc")
    assert viewer.wants(nile) and not viewer.wants(delta)
    assert ViewerClient("k", "club", "en").wants(delta)  # no club chosen: both


# --------------------------------------------------------------------------- Recap agent

@pytest.fixture(scope="module")
def bundle_overlays():
    return DemoBundle.load(ROOT / "demo" / "match_001.bundle.json").overlays()


@pytest.mark.parametrize("persona,lang,club", [("beginner", "en", None), ("tactical", "ar", None),
                                               ("player", "en", None), ("club", "ar", "delta_utd")])
def test_deterministic_recap_is_grounded(derby, bundle_overlays, persona, lang, club):
    recap = deterministic_recap(derby.metadata, bundle_overlays, persona=persona, language=lang, club_id=club)
    assert recap.final and "2-2" in recap.headline and recap.dir == ("rtl" if lang == "ar" else "ltr")
    assert recap.key_moments and all(m.overlay_id in {o["overlay_id"] for o in bundle_overlays} for m in recap.key_moments)
    goals = [m for m in recap.key_moments if m.facts.get("scorer_id")]
    assert len(goals) == 4  # goals always make the recap
    text = RecapText(headline=recap.headline[:80], body=" ".join(recap.body_lines)[:600].rsplit(".", 1)[0] + ".")
    assert verify_recap(text, recap, NameAllowlist(derby.metadata)) is None


def test_recap_so_far_and_rejections(derby, bundle_overlays):
    names = NameAllowlist(derby.metadata)
    half = deterministic_recap(derby.metadata, bundle_overlays, persona="tactical", language="en", until_s=2700)
    assert not half.final and half.headline.startswith("So far") and "1-1" in half.headline
    base = deterministic_recap(derby.metadata, bundle_overlays, persona="club", language="en", club_id="nile_fc")
    assert verify_recap(RecapText(headline="Nile FC draw 2-2", body="Nile FC hit 77 shots."), base, names) == "NUMBER_NOT_IN_EVIDENCE"
    assert verify_recap(RecapText(headline="Nile FC draw 2-2", body="Messi watched."), base, names) == "UNKNOWN_ENTITY"
    assert verify_recap(RecapText(headline="Nile FC draw 2-2", body="Delta United were rubbish."), base, names) == "TONE"
    assert verify_recap(RecapText(headline="A 2-2 draw", body="A good game."), base, names) == "TONE"  # club unnamed
    with pytest.raises(ValueError):
        deterministic_recap(derby.metadata, bundle_overlays, persona="club", language="en")


def test_recap_agent_approved_or_falls_back(derby, bundle_overlays):
    from backend.agents.llm import StubModel
    from backend.services.budget import DailyTokenBudget

    class Inventor(StubModel):
        name = "inventor"

        async def complete(self, system, user, json_schema=None):
            return json.dumps({"headline": "Full time: Nile FC 3-2 Delta United", "body": "What a match."}), 40

    async def go():
        budget = DailyTokenBudget(100000)
        good = await build_recap(derby.metadata, bundle_overlays, persona="beginner", language="ar",
                                 model=StubModel(), budget=budget)
        assert good.source == "agent" and good.verification_status == "approved"
        bad = await build_recap(derby.metadata, bundle_overlays, persona="beginner", language="en",
                                model=Inventor(), budget=budget)
        assert bad.source == "template" and bad.reason_code == "NUMBER_NOT_IN_EVIDENCE" and "2-2" in bad.headline
        broke = await build_recap(derby.metadata, bundle_overlays, persona="beginner", language="en",
                                  model=Inventor(), budget=DailyTokenBudget(0))
        assert broke.source == "template" and broke.reason_code == "MODEL_ERROR"
    asyncio.run(go())


# --------------------------------------------------------------------------- API routes

def test_health_reports_agents_and_mcp(client):
    h = client.get("/api/health").json()
    assert h["agents"]["mode"] == "off" and h["agents"]["club_persona"] is True
    assert h["mcp"]["mounted"] and h["mcp"]["path"] == "/mcp/"
    bundles = {b["match_id"]: b for b in h["demo_bundles"]}
    assert bundles["match_001"]["overlay_sources"] and not bundles["match_001"]["stale"]


def test_overlay_feed_demo_then_live(client):
    feed = client.get("/api/matches/match_001/overlays", params={"persona": "tactical", "lang": "ar"}).json()
    assert feed["source"] == "demo" and feed["count"] > 10 and feed["schema"] == "/api/spec/overlay"
    assert all(o["persona"] == "tactical" and o["dir"] == "rtl" for o in feed["overlays"])
    assert [o["show_at_s"] for o in feed["overlays"]] == sorted(o["show_at_s"] for o in feed["overlays"])
    later = client.get("/api/matches/match_001/overlays", params={"since": 3000}).json()
    assert later["count"] and all(o["show_at_s"] > 3000 for o in later["overlays"])
    club = client.get("/api/matches/match_001/overlays", params={"persona": "club", "club": "delta_utd"}).json()
    assert club["count"] and all(o["fields"]["club_id"] == "delta_utd" for o in club["overlays"])
    assert client.get("/api/matches/nope/overlays").status_code == 404

    client.post("/api/matches/match_001/start", params={"speed": 600, "from_minute": 62})
    with client.websocket_connect("/ws/matches/match_001?persona=club&lang=en&club=delta_utd&tracking_hz=0") as ws:
        msgs = collect(ws, lambda g: any(m["type"] == "overlay" for m in g))
    overlays = [m["data"] for m in msgs if m["type"] == "overlay"]
    assert overlays and all(o["persona"] == "club" and o["fields"]["club_id"] == "delta_utd" for o in overlays)
    live = client.get("/api/matches/match_001/overlays").json()
    assert live["source"] == "live" and live["run_id"] and live["count"] >= 10
    Overlay.model_validate(live["overlays"][0])
    assert client.get("/api/matches/match_001/overlays", params={"source": "demo"}).json()["source"] == "demo"


def test_recap_route_without_stored_recaps(client):
    # Exercise deterministic fallback independently of the shipped demo's cache.
    client.app.state.demo.bundles["match_001"].recaps.clear()
    r = client.get("/api/matches/match_001/recap", params={"persona": "player", "lang": "ar"}).json()
    assert r["dir"] == "rtl" and r["final"] and r["feed_source"] == "demo" and r["source"] == "template"
    r = client.get("/api/matches/match_001/recap", params={"persona": "club", "lang": "en", "club": "nile_fc"}).json()
    assert "Nile FC" in r["headline"] and r["club_id"] == "nile_fc"
    assert client.get("/api/matches/match_001/recap", params={"persona": "club"}).status_code == 422
    assert client.get("/api/matches/match_001/recap", params={"persona": "metric"}).status_code == 422


def test_break_it_route(client):
    r = client.post("/api/demo/break-it")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["status"] == "rejected" and body["verdict"]["reason_code"] == "NUMBER_NOT_IN_EVIDENCE"
    assert "999999" in body["draft"]["body"] and "999999" not in body["repaired_or_fallback_overlay"]["body"]
    assert body["moment_id"] == "mom_044" and body["show_at_s"] == 3783
    club = client.post("/api/demo/break-it", params={"persona": "club", "lang": "ar", "club": "delta_utd"}).json()
    assert club["repaired_or_fallback_overlay"]["fields"]["club_id"] == "delta_utd"
    assert client.post("/api/demo/break-it", params={"persona": "metric"}).status_code == 422
    assert client.post("/api/demo/break-it", params={"moment_id": "mom_99999"}).status_code == 404


# --------------------------------------------------------------------------- MCP client + Foundry auth

def test_mcp_client_matches_in_process_tools(derby, monkeypatch):
    from backend.agents.mcp_client import McpEvidenceTools
    from backend.agents.mcp_server import mcp_asgi_app
    from tests.test_agents_mcp import Library

    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")
    evidence = MatchEvidence(derby.metadata, derby.events, derby.frames)

    async def go():
        child = mcp_asgi_app(Library(derby), api_key="k")
        async with child.router.lifespan_context(child):
            def factory(key):
                return lambda headers: httpx.AsyncClient(transport=httpx.ASGITransport(child),
                                                         base_url="http://testserver", headers=headers)
            tools = McpEvidenceTools("http://testserver/", "k", http_client_factory=factory("k"))
            try:
                assert len(await tools.list_tools()) == 7
                assert await tools.get_moment_evidence("match_001", "mom_044") == evidence.evidence("mom_044")
                assert await tools.get_match_state("match_001", 3783) == evidence.state_at(3783)
                assert await tools.get_recent_events("match_001", 3783, 300) == evidence.recent_events(3783, 300, limit=50)
                assert (await tools.get_player_statistics("match_001", "nil_10", 3783)) == evidence.player_stats("nil_10", 3783)
                with pytest.raises(Exception):
                    await tools.get_moment_evidence("match_001", "mom_99999")
            finally:
                await tools.aclose()
            bad = McpEvidenceTools("http://testserver/", "wrong", http_client_factory=factory("wrong"))
            with pytest.raises(BaseException):
                await bad.list_tools()
            await bad.aclose()
    asyncio.run(go())


def test_mcp_transport_is_selected_by_config(monkeypatch):
    from backend.agents.config import AgentConfig
    from backend.agents.mcp_client import McpEvidenceTools
    from backend.agents.workflow import WorkflowRunner
    from backend.services.budget import DailyTokenBudget

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("AGENT_TOOLS", "mcp")
    config = AgentConfig.from_env()
    runner = WorkflowRunner(SimpleNamespace(budget=DailyTokenBudget(0)), config)
    assert isinstance(runner.tools, McpEvidenceTools) and runner.tools.url == "http://127.0.0.1:8000/mcp/"
    monkeypatch.setenv("AGENT_TOOLS", "carrier-pigeon")
    with pytest.raises(ValueError):
        AgentConfig.from_env()


def test_foundry_key_auth_for_cross_tenant_deployments():
    from backend.agents.config import AgentConfig
    from backend.agents.llm import create_model

    config = AgentConfig(mode="foundry", foundry_project_endpoint="https://res.services.ai.azure.com/api/projects/p",
                         model_fast="fast-dep", model_strong="strong-dep", foundry_api_key="super-secret")
    assert "super-secret" not in repr(config)
    model = create_model(config)
    assert model.auth == "key" and "super-secret" not in repr(model)
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers.get("api-key"),
                    bearer=request.headers.get("authorization"), body=json.loads(request.content))
        return httpx.Response(200, json={
            "id": "r", "object": "response", "created_at": 1, "status": "completed", "model": "fast-dep",
            "output": [{"type": "message", "id": "m", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": "{\"ok\":true}", "annotations": []}]}],
            "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": []})

    async def go():
        await model.prepare()  # no token request, no network
        model._client.client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        text, tokens = await model.complete("system", "user", {"type": "object"})
        assert json.loads(text) == {"ok": True} and tokens == 12
        await model.aclose()
    asyncio.run(go())
    assert seen["url"].startswith("https://res.services.ai.azure.com/openai/v1/responses")
    assert seen["key"] == "super-secret" and seen["bearer"] is None
    assert seen["body"]["model"] == "fast-dep" and seen["body"]["store"] is False
    with pytest.raises(ValueError):
        create_model(AgentConfig(mode="foundry", foundry_project_endpoint=config.foundry_project_endpoint,
                                 model_fast="x", foundry_api_key="k", foundry_openai_endpoint="https://evil.example/"))


# --------------------------------------------------------------------------- evals + deployment config

def test_eval_runner_proves_the_verifier_gate():
    from evals.run_agent_eval import main_async

    args = SimpleNamespace(mode="stub", limit=12, inject=0.5, seed=3, token_cap=10**6, foundry_evaluators=False,
                           no_write=True, quiet=True)
    summary = asyncio.run(main_async(args))
    assert summary["injected"] > 0 and summary["raw_numeric_faithfulness_pct"] < 100
    assert summary["final_numeric_faithfulness_pct"] == 100.0 and summary["injected_caught_pct"] == 100.0
    assert summary["rejections_by_reason"].get("NUMBER_NOT_IN_EVIDENCE") == summary["injected"]
    assert {k.split("/")[0] for k in summary["by_persona_language"]} >= {"beginner", "tactical", "club"}


def test_numeric_faithfulness_evaluator():
    from evals.numeric_faithfulness import NumericFaithfulnessEvaluator

    ev = NumericFaithfulnessEvaluator()
    assert ev(response="Shot speed ١٠٤ km/h, 54.6% possession", context={"shot_speed_kmh": 104, "p": 0.546})["numeric_faithfulness"] == 1.0
    bad = ev(response="Shot speed 140 km/h", context=json.dumps({"shot_speed_kmh": 104}))
    assert bad["numeric_faithfulness"] == 0.0 and "140" in bad["unsupported_numbers"]


def test_integration_env_classifies_secrets(tmp_path):
    script = ROOT / "deployment" / "integration_env.py"
    env = tmp_path / "integration.env"
    env.write_text("AGENT_MODE=foundry\nFOUNDRY_API_KEY=abc\nMCP_API_KEY=m\nCOSMOS_ENDPOINT=https://c/\n# c\n", encoding="utf-8")

    def run(*args):
        return subprocess.run([sys.executable, str(script), str(env), *args], capture_output=True, text=True, check=True).stdout

    assert "FOUNDRY_API_KEY=secretref:foundry-api-key" in run("env") and "abc" not in run("env")
    assert sorted(run("secrets").split()) == ["foundry-api-key=abc", "mcp-api-key=m"]
    cfg = json.loads(run("bicep"))
    assert cfg["params"]["agentMode"] == "foundry" and set(cfg["secretEnv"]) == {"FOUNDRY_API_KEY", "MCP_API_KEY"}
    assert cfg["extraEnv"] == [{"name": "COSMOS_ENDPOINT", "value": "https://c/"}]
    env.write_text("PIPELINE_PLUGINS=backend.api.template_plugin:register,backend.agents.plugin:register\nMCP_API_KEY=m\n")
    assert subprocess.run([sys.executable, str(script), str(env), "env"], capture_output=True).returncode != 0


def test_committed_demo_bundles_carry_the_whole_pipeline():
    for path in sorted((ROOT / "demo").glob("*.bundle.json")):
        bundle = DemoBundle.load(path)
        assert bundle.plugins == PLUGINS, path.name
        personas = {o["persona"] for o in bundle.overlays()}
        assert personas == {"beginner", "tactical", "player", "club"}, path.name
        assert {o["language"] for o in bundle.overlays()} == {"en", "ar"}
        assert all(o["verification_status"] in ("approved", "fallback") for o in bundle.overlays())
        assert len({o["overlay_id"] for o in bundle.overlays()}) == len(bundle.overlays())


def test_bicep_and_example_files_are_in_sync():
    bicep = (ROOT / "deployment" / "azure" / "main.bicep").read_text(encoding="utf-8")
    for param in ("agentMode", "secretEnv", "deployAppInsights", "cosmosAccountName", "agentTools"):
        assert f"param {param}" in bicep
    assert "backend.analytics.plugin:register,backend.agents.plugin:register" in bicep
    example = Path(ROOT / "deployment" / "integration.env.example").read_text(encoding="utf-8")
    assert "template_plugin:register\n" not in example.replace("# ", "")
