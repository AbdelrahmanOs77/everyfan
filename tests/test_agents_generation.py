"""Phase 4 stages: bounded evidence, budgeted models, and concurrent persona drafts."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.agents.analyst import analyze
from backend.agents.config import AgentConfig
from backend.agents.llm import FoundryModel, StubModel, complete_with_budget, create_model
from backend.agents.names import NameAllowlist
from backend.agents.producer import produce
from backend.agents.verifier import brief_from_moment, verify
from backend.agents.writers import write_overlays
from backend.services.budget import DailyTokenBudget
from tests.test_agents_templates import ROWS, eval_moment


@pytest.fixture
def goal(derby):
    moment = eval_moment(next(r for r in ROWS if r["match_id"] == "match_001" and r["moment_id"] == "mom_044"))
    return moment, NameAllowlist(derby.metadata)


class Tools:
    def __init__(self, moment):
        self.moment = moment
        self.calls = []

    async def get_moment_evidence(self, match_id, moment_id):
        self.calls.append(("evidence", match_id, moment_id))
        return {"moment": self.moment.model_dump(), "facts": self.moment.verified_facts}

    async def get_match_state(self, match_id, at_s):
        self.calls.append(("state", match_id, at_s))
        return {"match_id": match_id, "game_clock_s": at_s, "teams": {"nile_fc": {"ppda_match": 4.3}}}

    async def compare_to_baseline(self, **kwargs):
        self.calls.append(("baseline", kwargs))
        return {"current": 1.8, "match_baseline": 4.3}

    async def get_player_statistics(self, **kwargs):
        self.calls.append(("player", kwargs))
        return {"shots": 3}


def test_producer_personas_cooldown_and_urgent_events(goal):
    moment, _ = goal
    history = {}
    plan = produce(moment, history)
    assert len(plan) == 6
    assert all(i.priority == 1 and i.ttl_s == 8 for i in plan)
    assert {(i.persona, i.language) for i in plan} == {(p, l) for p in ("beginner", "tactical", "player") for l in ("en", "ar")}
    quiet = moment.model_copy(update={"type": "big_chance", "game_clock_s": moment.game_clock_s + 44})
    assert produce(quiet, history) == []
    later = quiet.model_copy(update={"game_clock_s": moment.game_clock_s + 45})
    assert len(produce(later, history)) == 6
    red = quiet.model_copy(update={"type": "red_card"})
    assert len(produce(red, history)) == 6  # urgent events ignore cooldown
    other = quiet.model_copy(update={"match_id": "match_002"})
    assert len(produce(other, history)) == 6
    no_player = moment.model_copy(update={"type": "rhythm_change", "player_id": None, "verified_facts": {}})
    assert len(produce(no_player, {})) == 4
    assert produce(no_player.model_copy(update={"importance": 0.49}), {}) == []
    assert next(i for i in plan if i.persona == "tactical").slot == "side_panel"
    assert next(i for i in plan if i.persona == "beginner").template_id == "lower_third"


def test_analyst_stub_prefetch_and_off_mode(goal):
    moment, _ = goal

    async def go():
        tools = Tools(moment)
        brief = await analyze(moment, tools, StubModel(), DailyTokenBudget(50000))
        assert brief.facts == moment.verified_facts
        assert brief.focus_player_id == moment.player_id
        assert len(tools.calls) == 2
        tools.calls.clear()
        assert (await analyze(moment, tools)).facts == moment.verified_facts
        assert tools.calls == []

    asyncio.run(go())


def test_analyst_filters_invented_and_mislabelled_facts(goal):
    moment, _ = goal

    class Invented(StubModel):
        async def complete(self, system, user, json_schema=None):
            brief = brief_from_moment(moment).model_dump()
            brief["facts"].update(invented=999, mislabelled=104, ppda_match=4.3, shot_speed_kmh=999)
            brief["claim"] = "A 999 km/h shot."
            return json.dumps(brief), 40

    class OtherContext(Tools):
        async def get_match_state(self, match_id, at_s):
            state = await super().get_match_state(match_id, at_s)
            state["other_player"] = {"shot_speed_kmh": 999}
            return state

    async def go():
        budget = DailyTokenBudget(50000)
        brief = await analyze(moment, OtherContext(moment), Invented(), budget)
        assert "invented" not in brief.facts and "mislabelled" not in brief.facts
        assert brief.facts["ppda_match"] == 4.3
        assert brief.facts["shot_speed_kmh"] == 104
        assert "999" not in brief.claim and brief.confidence == "low"
        assert budget.used == 40 and budget.reserved == 0

    asyncio.run(go())


@pytest.mark.parametrize("bad", ["too_many", "future", "other_match", "unknown_tool"])
def test_analyst_rejects_unsafe_tool_requests_without_executing_them(goal, bad):
    moment, _ = goal

    class Requests(StubModel):
        async def complete(self, system, user, json_schema=None):
            call = {"name": "get_player_statistics", "arguments": {"player_id": "nil_10"}}
            if bad == "future":
                call["arguments"]["at_s"] = 5400
            if bad == "other_match":
                call["arguments"]["match_id"] = "match_002"
            if bad == "unknown_tool":
                call["name"] = "delete_match"
            return json.dumps({"tool_calls": [call] * (3 if bad == "too_many" else 1)}), 5

    async def go():
        tools = Tools(moment)
        brief = await analyze(moment, tools, Requests(), DailyTokenBudget(50000))
        assert brief.facts == moment.verified_facts and brief.confidence == "low"
        assert len(tools.calls) == 2  # only the two mandatory prefetches

    asyncio.run(go())


def test_analyst_allows_two_extra_tools_then_returns_grounded_brief(goal):
    moment, _ = goal

    class Requests(StubModel):
        calls = 0

        async def complete(self, system, user, json_schema=None):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"tool_calls": [
                    {"name": "compare_to_baseline", "arguments": {"metric": "ppda", "window_s": 300}},
                    {"name": "get_player_statistics", "arguments": {"player_id": "nil_10"}},
                ]}), 10
            payload = json.loads(user)
            assert len(payload["tool_results"]) == 2
            brief = payload["brief"]
            brief["facts"]["current"] = 1.8
            return json.dumps(brief), 20

    async def go():
        tools = Tools(moment)
        budget = DailyTokenBudget(50000)
        brief = await analyze(moment, tools, Requests(), budget)
        assert brief.facts["current"] == 1.8
        extras = tools.calls[2:]
        assert len(extras) == 2
        assert all(c[1]["match_id"] == moment.match_id and c[1]["at_s"] == moment.game_clock_s for c in extras)
        assert budget.used == 30 and budget.reserved == 0

    asyncio.run(go())


def test_analyst_deadline_and_exhausted_budget_fall_back(goal):
    moment, _ = goal

    class Slow(StubModel):
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(1)

    async def go():
        model = Slow()
        brief = await analyze(moment, Tools(moment), model, DailyTokenBudget(0))
        assert brief.confidence == "low" and model.calls == 0
        budget = DailyTokenBudget(50000)
        brief = await analyze(moment, Tools(moment), model, budget, timeout_s=0.01)
        assert brief.facts == moment.verified_facts and brief.confidence == "low"
        assert budget.reserved == 0
        # The deadline can expire in prefetch; charge only if a model call started.
        assert budget.used > 0 if model.calls else budget.used == 0

    asyncio.run(go())


@pytest.mark.parametrize("reply", ["not json", "[]", "{}"])
def test_analyst_bad_output_falls_back_without_leaking_reservations(goal, reply):
    moment, _ = goal

    class Malformed(StubModel):
        async def complete(self, *args, **kwargs):
            return reply, 12

    async def go():
        budget = DailyTokenBudget(50000)
        brief = await analyze(moment, Tools(moment), Malformed(), budget)
        assert brief.facts == moment.verified_facts and brief.confidence == "low"
        assert budget.used == 12 and budget.reserved == 0

    asyncio.run(go())


def test_writers_stub_create_six_grounded_bilingual_pending_drafts(goal):
    moment, names = goal

    async def go():
        plan = produce(moment, {})
        results = await write_overlays(brief_from_moment(moment), moment, names, plan, StubModel(), DailyTokenBudget(100000), trace_id="phase4-test")
        assert len(results) == 6 and all(r.error is None for r in results)
        for result in results:
            overlay = result.draft
            assert overlay.source == "agent" and overlay.verification_status == "rejected"
            assert overlay.trace_id == "phase4-test" and overlay.model == "stub"
            assert overlay.show_at_s == moment.game_clock_s
            assert overlay.prompt_version == f"writer_{overlay.persona}_v1"
            assert verify(overlay.model_dump(), brief_from_moment(moment), moment, names, overlay.persona).status == "approved"
            if overlay.language == "ar":
                assert overlay.dir == "rtl" and "حسن نور" in overlay.headline + overlay.body

    asyncio.run(go())


@pytest.mark.parametrize("row", list({r["type"]: r for r in ROWS}.values()), ids=lambda r: r["type"])
def test_stub_drafts_for_each_eval_moment_type(row, matches):
    moment = eval_moment(row)
    match = next(m for m in matches.values() if m.metadata.match_id == moment.match_id)
    names = NameAllowlist(match.metadata)

    async def go():
        brief = brief_from_moment(moment)
        plan = produce(moment, {})
        results = await write_overlays(brief, moment, names, plan, StubModel(), DailyTokenBudget(100000))
        assert results and all(r.draft is not None and r.error is None for r in results)
        for result in results:
            assert verify(result.draft.model_dump(), brief, moment, names, result.item.persona).status == "approved"

    asyncio.run(go())


def test_writers_run_concurrently_and_isolate_failure(goal):
    moment, names = goal

    class Concurrent(StubModel):
        active = 0
        peak = 0

        async def complete(self, system, user, json_schema=None):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                if json.loads(user)["persona"] == "player":
                    return '{"headline":"x","body":"x","fields":{},"priority":5}', 0
                return await super().complete(system, user, json_schema)
            finally:
                self.active -= 1

    async def go():
        model = Concurrent()
        results = await write_overlays(brief_from_moment(moment), moment, names, produce(moment, {}), model, DailyTokenBudget(100000))
        assert model.peak == 6
        assert sum(r.draft is not None for r in results) == 4
        assert all(r.error == "INVALID_DRAFT" for r in results if r.item.persona == "player")

    asyncio.run(go())


def test_writers_cannot_choose_player_id_or_runtime_measurements(goal):
    moment, names = goal

    class Fields(StubModel):
        async def complete(self, system, user, json_schema=None):
            text, tokens = await super().complete(system, user, json_schema)
            draft = json.loads(text)
            draft["fields"].update(player_id="nil_09", generated_ms=999999, budget_ms=999999)
            return json.dumps(draft), tokens

    async def go():
        results = await write_overlays(brief_from_moment(moment), moment, names, produce(moment, {}), Fields(), DailyTokenBudget(100000))
        for result in results:
            assert result.draft.fields["generated_ms"] != 999999
            assert result.draft.fields["budget_ms"] == 2000
            if result.item.persona == "player":
                assert result.draft.fields["player_id"] == "nil_10"

    asyncio.run(go())


def test_writer_budget_denial_off_mode_and_deadline(goal):
    moment, names = goal

    class Slow(StubModel):
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(1)

    async def go():
        plan = produce(moment, {})
        model = Slow()
        results = await write_overlays(brief_from_moment(moment), moment, names, plan, model, DailyTokenBudget(0))
        assert model.calls == 0 and all(r.error == "BUDGET" for r in results)
        budget = DailyTokenBudget(100000)
        results = await write_overlays(brief_from_moment(moment), moment, names, plan, None, budget)
        assert all(r.error == "OFF" for r in results) and budget.used == 0
        results = await write_overlays(brief_from_moment(moment), moment, names, plan, model, budget, timeout_s=0.02)
        assert all(r.error == "TIMEOUT" for r in results)
        assert model.calls == 6 and budget.reserved == 0

    asyncio.run(go())


def test_mode_factory_and_foundry_adapter_are_lazy_and_use_real_usage():
    assert create_model(AgentConfig(mode="off")) is None
    assert isinstance(create_model(AgentConfig(mode="stub")), StubModel)
    config = AgentConfig(mode="foundry", foundry_project_endpoint="https://test.services.ai.azure.com/api/projects/test",
                         model_fast="fast-test", model_strong="strong-test")
    assert create_model(config).name == "fast-test"
    assert create_model(config, "strong").name == "strong-test"
    with pytest.raises(ValueError):
        create_model(config, "bogus")
    with pytest.raises(ValueError):
        FoundryModel("https://attacker.example/api/projects/test", "fast-test")

    class Client:
        async def get_response(self, messages, *, options):
            assert len(messages) == 2 and messages[0].role == "system"
            if "response_format" in options:
                assert options["response_format"] == {"type": "json_object"}
            assert options["store"] is False
            return SimpleNamespace(text='{"ok":true}', usage_details={"total_token_count": 17})

    async def go():
        model = FoundryModel("https://test.services.ai.azure.com/api/projects/test", "test-deployment", client=Client())
        text, tokens = await model.complete("system", "user", {"type": "object"})
        assert json.loads(text) == {"ok": True} and tokens == 17
        budget = DailyTokenBudget(10000)
        await complete_with_budget(model, "system", "user", budget=budget)
        assert budget.used == 17 and budget.reserved == 0

    asyncio.run(go())


def test_cancelled_model_call_settles_reservation():
    class Blocked(StubModel):
        def __init__(self):
            self.started = asyncio.Event()

        async def complete(self, *args, **kwargs):
            self.started.set()
            await asyncio.Event().wait()

    async def go():
        model, budget = Blocked(), DailyTokenBudget(10000)
        task = asyncio.create_task(complete_with_budget(model, "system", "user", budget=budget))
        await asyncio.wait_for(model.started.wait(), 1)
        assert budget.reserved > 0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert budget.reserved == 0 and budget.used > 0

    asyncio.run(go())
