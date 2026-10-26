"""Owner C fallback acceptance: full eval set, milestones, and real replay."""

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

from backend.agents.names import NameAllowlist
from backend.agents.templates import template_overlays
from shared.schemas import Moment, Overlay
from shared.schemas.contracts import MomentType


ROWS = [json.loads(line) for line in
        (Path(__file__).resolve().parents[1] / "evals/moments_eval.jsonl").read_text(encoding="utf-8").splitlines()]


def eval_moment(row):
    return Moment(moment_id=row["moment_id"], match_id=row["match_id"],
                  game_clock_s=row["state"]["game_clock_s"], type=row["type"], importance=row["importance"],
                  team_id=row["team_id"], player_id=row["player_id"], evidence_event_ids=row["evidence_event_ids"],
                  verified_facts=row["facts"], rule_id=row["rule_id"])


@pytest.fixture(scope="module")
def names_by_match(matches):
    return {m.metadata.match_id: NameAllowlist(m.metadata) for m in matches.values()}


@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['match_id']}-{r['moment_id']}")
def test_every_eval_moment_has_grounded_bilingual_templates(row, names_by_match):
    moment = eval_moment(row)
    names = names_by_match[moment.match_id]
    overlays = template_overlays(moment, names)
    personas = {"beginner", "tactical", "player"} if moment.player_id else {"beginner", "tactical"}
    assert {(o.persona, o.language) for o in overlays} == {(p, lang) for p in personas for lang in ("en", "ar")}
    for ov in overlays:
        assert Overlay.model_validate(ov.model_dump()) == ov
        assert len(ov.headline) <= 60 and len(ov.body) <= 160
        assert ov.dir == ("rtl" if ov.language == "ar" else "ltr")
        assert ov.overlay_id == f"ov_{moment.moment_id}_{ov.persona}_{ov.language}"
        assert ov.show_at_s == moment.game_clock_s
        assert ov.source == "template" and ov.verification_status == "fallback"
        assert set(ov.evidence_event_ids) <= set(moment.evidence_event_ids)
        assert "None" not in ov.body and "None" not in ov.headline
        allowed_numbers = [float(v) for v in moment.verified_facts.values()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)]
        for number in re.findall(r"\d+(?:\.\d+)?", ov.headline + " " + ov.body):
            assert any(abs(float(number) - fact) < 0.001 for fact in allowed_numbers)
        if ov.persona == "player":
            assert ov.fields["player_id"] == moment.player_id
            assert names.player(moment.player_id, ov.language) in ov.headline + ov.body
        if ov.language == "ar" and moment.player_id:
            assert names.player(moment.player_id, "ar") in ov.headline + ov.body


def test_all_nine_types_including_low_importance_milestones(derby):
    from backend.analytics.evidence import MatchEvidence

    names = NameAllowlist(derby.metadata)
    seen = set()
    evidence = MatchEvidence(derby.metadata, derby.events, derby.frames)
    for moment in evidence.moments:
        overlays = template_overlays(moment, names)
        assert overlays
        seen.add(moment.type)
    # The derby has no red card; its template is covered by the eval set.
    assert seen | {r["type"] for r in ROWS} == set(get_args(MomentType))


def test_red_card_never_invents_remaining_time(names_by_match):
    row = next(r for r in ROWS if r["type"] == "red_card")
    overlays = template_overlays(eval_moment(row), names_by_match[row["match_id"]])
    tactical = next(o for o in overlays if o.persona == "tactical" and o.language == "en")
    assert "30" not in tactical.body  # Owner A's template computes remaining minutes; C must use evidence.
    assert "10" in tactical.body


def test_name_allowlist_uses_metadata(derby):
    names = NameAllowlist(derby.metadata)
    assert names.player("nil_10", "ar") == "حسن نور"
    assert names.player("nil_10", "en") == "Hassan Nour"
    assert "Hassan Nour" in names.allowed
    assert "حسن نور" in names.allowed
    assert derby.metadata.home.short_name in names.allowed


def test_plugin_requires_analytics_first():
    from backend.agents.plugin import register

    with pytest.raises(RuntimeError, match="analytics"):
        register(SimpleNamespace())


def test_plugin_publishes_only_agent_worthy_moments_and_resets(derby):
    from backend.agents.plugin import register
    from backend.api.hub import ViewerHub
    from backend.api.plugins import PipelineContext
    from backend.services.budget import DailyTokenBudget

    async def go():
        ctx = PipelineContext(ViewerHub(0), DailyTokenBudget(0))
        callbacks = []
        ctx.analytics = SimpleNamespace(subscribe=callbacks.append)
        ctx.recording = []
        register(ctx)
        state = SimpleNamespace(match_id=derby.metadata.match_id, metadata=derby.metadata, run_id="run_a")
        await ctx.dispatch(ctx.reset_handlers, state)
        moment = eval_moment(next(r for r in ROWS if r["match_id"] == state.match_id and r["type"] == "goal"))
        moment = moment.model_copy(update={"importance": 0.5})
        callbacks[0](moment.model_copy(update={"importance": 0.49}), state)
        await ctx.drain()
        assert ctx.recording == []
        callbacks[0](moment, state)
        callbacks[0](moment, state)
        await ctx.drain()
        # 3 personas x 2 languages, plus Favorite Club for each of the 2 clubs x 2 languages.
        assert len(ctx.recording) == 10
        assert sum(i["data"]["persona"] == "club" for i in ctx.recording) == 4
        assert ctx.errors == 0
        state.run_id = "run_b"
        await ctx.dispatch(ctx.reset_handlers, state)
        callbacks[0](moment, state)
        await ctx.drain()
        assert len(ctx.recording) == 20
        assert ctx.budget.used == 0
        # Reset before a queued publisher runs: the previous run must not leak overlays.
        state.run_id = "run_c"
        await ctx.dispatch(ctx.reset_handlers, state)
        callbacks[0](moment, state)
        state.run_id = "run_d"
        await ctx.dispatch(ctx.reset_handlers, state)
        await ctx.drain()
        assert len(ctx.recording) == 20

    asyncio.run(go())


def test_config_defaults_and_validation(monkeypatch):
    from backend.agents.config import AgentConfig

    for key in ("AGENT_MODE", "AGENT_TOTAL_TIMEOUT_S", "MCP_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert AgentConfig.from_env().mode == "off"
    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("MCP_API_KEY", "private-test-key")
    assert "private-test-key" not in repr(AgentConfig.from_env())
    for bad in ("0", "-1", "nan", "inf"):
        monkeypatch.setenv("AGENT_TOTAL_TIMEOUT_S", bad)
        with pytest.raises(ValueError):
            AgentConfig.from_env()
    monkeypatch.delenv("AGENT_TOTAL_TIMEOUT_S")
    monkeypatch.setenv("AGENT_MODE", "typo")
    with pytest.raises(ValueError, match="AGENT_MODE"):
        AgentConfig.from_env()


def test_stub_model_returns_supplied_grounded_json():
    from backend.agents.llm import StubModel

    async def go():
        model = StubModel()
        draft = {"headline": "Goal", "body": "A verified goal.", "fields": {}}
        text, tokens = await model.complete("writer", json.dumps({"task": "writer", "template": draft}))
        assert json.loads(text) == draft and tokens == 0
        text, tokens = await model.complete("analyst", json.dumps({"task": "analyst", "brief": {"facts": {"minute": 13}}}))
        assert json.loads(text) == {"facts": {"minute": 13}} and tokens == 0
        with pytest.raises(ValueError, match="Unsupported"):
            await model.complete("", '{"task":"unknown"}')

    asyncio.run(go())


def test_real_replay_records_templates_at_moment_time(derby):
    from backend.api.demo import build_bundle
    from backend.api.hub import ViewerHub
    from backend.api.plugins import PipelineContext, load_plugins
    from backend.services.budget import DailyTokenBudget

    async def go():
        ctx = PipelineContext(ViewerHub(0), DailyTokenBudget(0))
        load_plugins(ctx, ["backend.analytics.plugin:register", "backend.agents.plugin:register"])
        bundle = await build_bundle(derby, ctx)
        moments = {i["data"]["moment_id"]: Moment.model_validate(i["data"])
                   for i in bundle.items if i["type"] == "moment" and i["data"]["importance"] >= 0.5}
        overlays = [Overlay.model_validate(i["data"]) for i in bundle.items if i["type"] == "overlay"]
        assert overlays and ctx.errors == 0
        from backend.agents.producer import produce
        history = {}
        clubs = (derby.metadata.home.team_id, derby.metadata.away.team_id)
        scheduled = {mid for mid, moment in moments.items() if produce(moment, history, clubs)}
        assert {o.moment_id for o in overlays} == scheduled
        assert len({o.overlay_id for o in overlays}) == len(overlays)
        assert all(o.show_at_s == moments[o.moment_id].game_clock_s for o in overlays)

    asyncio.run(go())
