"""Deterministic verifier acceptance and adversarial regression cases, entirely offline."""

import asyncio
import json

import pytest

from backend.agents.breakit import make_adversarial_draft, run_break_it
from backend.agents.names import NameAllowlist, focus_player
from backend.agents.templates import template_overlays
from backend.agents.verifier import brief_from_moment, verify, verify_with_model
from shared.schemas import Overlay
from tests.test_agents_templates import ROWS, eval_moment


@pytest.fixture(scope="module")
def names_by_match(matches):
    return {m.metadata.match_id: NameAllowlist(m.metadata) for m in matches.values()}


@pytest.fixture
def goal(names_by_match):
    row = next(r for r in ROWS if r["match_id"] == "match_001" and r["type"] == "goal"
               and r["facts"].get("scorer_id") == "nil_10")
    moment = eval_moment(row)
    names = names_by_match[moment.match_id]
    brief = brief_from_moment(moment)
    overlays = template_overlays(moment, names)
    return moment, names, brief, {(o.persona, o.language): o.model_dump() for o in overlays}


@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['match_id']}-{r['moment_id']}")
def test_correct_templates_approved_across_entire_eval_set(row, names_by_match):
    moment = eval_moment(row)
    names = names_by_match[moment.match_id]
    for overlay in template_overlays(moment, names):
        verdict = verify(overlay.model_dump(), brief_from_moment(moment), moment, names, overlay.persona)
        assert verdict.status == "approved", (overlay, verdict)


@pytest.mark.parametrize("lang,number", [("en", "999"), ("ar", "٩٩٩"), ("ar", "۹۹۹"), ("ar", "٩٩٩٫٥")])
def test_invented_numbers_rejected_in_both_languages(goal, lang, number):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", lang]
    draft["headline"] = "Goal" if lang == "en" else "هدف"
    draft["body"] = f"{number} km/h" if lang == "en" else f"سرعة التسديدة {number} كم/س"
    assert verify(draft, brief, moment, names, "tactical").reason_code == "NUMBER_NOT_IN_EVIDENCE"


@pytest.mark.parametrize("text", ["Hassan Nour hit 104 km/h.", "حسن نور سدد بسرعة ١٠٤ كم/س.", "حسن نور سدد بسرعة ۱۰۴ كم/س."])
def test_correct_arabic_and_western_numbers_are_accepted(goal, text):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", "ar" if "حسن" in text else "en"]
    draft["body"] = text
    assert verify(draft, brief, moment, names, "tactical").status == "approved"


@pytest.mark.parametrize("text", ["Lionel Messi scored.", "Messi scored.", "ليونيل ميسي سجل الهدف.", "نادي برشلونة سجل الهدف."])
def test_unknown_entities_rejected(goal, text):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", "en"]
    draft["body"] = text
    assert verify(draft, brief, moment, names, "tactical").reason_code == "UNKNOWN_ENTITY"


@pytest.mark.parametrize("updates,reason", [
    ({"headline": "a" * 61}, "TOO_LONG"),
    ({"body": "a" * 161}, "TOO_LONG"),
    ({"slot": "invalid"}, "SCHEMA"),
    ({"evidence_event_ids": ["evt_99999"]}, "BAD_EVIDENCE_ID"),
    ({"moment_id": "mom_999"}, "SCHEMA"),
    ({"match_id": "match_999"}, "SCHEMA"),
    ({"show_at_s": 0}, "SCHEMA"),
    ({"dir": "rtl"}, "SCHEMA"),
    ({"persona": "beginner"}, "SCHEMA"),
])
def test_schema_identity_timing_and_evidence_guards(goal, updates, reason):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", "en"]
    draft.update(updates)
    assert verify(draft, brief, moment, names, "tactical").reason_code == reason


def test_foreign_brief_or_metadata_is_rejected(goal):
    moment, names, brief, drafts = goal
    verdict = verify(drafts["tactical", "en"], brief.model_copy(update={"match_id": "match_999"}), moment, names, "tactical")
    assert verdict.reason_code == "SCHEMA"
    brief = brief.model_copy(update={"match_id": moment.match_id, "evidence_event_ids": ["evt_99999"]})
    assert verify(drafts["tactical", "en"], brief, moment, names, "tactical").reason_code == "BAD_EVIDENCE_ID"


@pytest.mark.parametrize("text,accepted", [
    ("PPDA is 4.", False),
    ("PPDA means passes allowed per defensive action.", True),
    ("PPDA — passes allowed per defensive action.", True),
    ("PPDA means passes allowed. PPDA improves.", False),
    ("ضغط عكسي قوي.", False),
    ("ضغط عكسي يعني محاولة استعادة الكرة بعد فقدانها.", True),
])
def test_beginner_jargon_must_be_explained_each_time(goal, text, accepted):
    moment, names, brief, drafts = goal
    draft = drafts["beginner", "en"]
    draft["body"] = text
    # Keep every number valid so this test isolates persona rules.
    draft["body"] = draft["body"].replace("4.", "104.")
    verdict = verify(draft, brief, moment, names, "beginner")
    assert verdict.status == ("approved" if accepted else "rejected")
    if not accepted:
        assert verdict.reason_code == "TONE"


def test_player_requires_focus_id_and_mention(goal):
    moment, names, brief, drafts = goal
    draft = drafts["player", "en"]
    assert draft["fields"]["player_id"] == focus_player(moment)
    draft["fields"]["player_id"] = "nil_09"
    assert verify(draft, brief, moment, names, "player").reason_code == "TONE"
    draft["fields"]["player_id"] = focus_player(moment)
    draft["headline"], draft["body"] = "Goal", "A goal was scored."
    assert verify(draft, brief, moment, names, "player").reason_code == "TONE"


@pytest.mark.parametrize("value,text,accepted", [
    (1.84, "PPDA 1.8", True),
    (1.84, "PPDA ١٫٨", True),
    (1.84, "PPDA 1.7", False),
    (53.9, "Possession 54%", True),
    (53.9, "Possession 54 km/h", False),
    (0.539, "Possession 54%", True),
    (0.539, "Possession 53.9%", True),
    (104, "Shot speed 104.04 km/h", True),
    (104, "Shot speed 105 km/h", False),
    (1.84, "PPDA 2", False),
    (True, "Shot speed 1 km/h", False),
])
def test_numeric_rounding_percentage_and_boolean_rules(goal, value, text, accepted):
    moment, names, brief, drafts = goal
    # Use a non-goal to avoid score/minute derived values accidentally allowing a bad integer.
    moment = moment.model_copy(update={"type": "pressing_shift", "verified_facts": {"metric": value}})
    brief = brief.model_copy(update={"facts": {"metric": value}})
    draft = drafts["tactical", "en"]
    draft["headline"], draft["body"] = "Pressing", text
    draft["fields"] = {}
    assert verify(draft, brief, moment, names, "tactical").status == ("approved" if accepted else "rejected")


@pytest.mark.parametrize("invented", [999, "999", "٩٩٩ كم/س"])
def test_numbers_inside_fields_are_checked_but_generation_metadata_is_exempt(goal, invented):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", "en"]
    draft["fields"]["shot_speed_kmh"] = invented
    assert verify(draft, brief, moment, names, "tactical").reason_code == "NUMBER_NOT_IN_EVIDENCE"
    draft["fields"]["shot_speed_kmh"] = 104
    draft["fields"].update(generated_ms=3562, budget_ms=5500)
    assert verify(draft, brief, moment, names, "tactical").status == "approved"


def test_optional_semantic_check_fails_closed_and_skips_stub(goal):
    moment, names, brief, drafts = goal

    class Model:
        name = "test"
        calls = 0

        async def complete(self, system, user, json_schema=None):
            self.calls += 1
            return json.dumps({"status": "rejected", "reason_code": "UNSUPPORTED_CAUSALITY", "detail": "Not supported."}), 10

    async def go():
        from backend.services.budget import DailyTokenBudget

        budget = DailyTokenBudget(10000)
        model = Model()
        verdict = await verify_with_model(drafts["tactical", "en"], brief, moment, names, "tactical", model=model, budget=budget)
        assert verdict.reason_code == "UNSUPPORTED_CAUSALITY" and model.calls == 1
        assert budget.used == 10 and budget.reserved == 0
        bad = {**drafts["tactical", "en"], "body": "999 km/h"}
        assert (await verify_with_model(bad, brief, moment, names, "tactical", model=model)).reason_code == "NUMBER_NOT_IN_EVIDENCE"
        assert model.calls == 1
        model.name = "stub"
        assert (await verify_with_model(drafts["tactical", "en"], brief, moment, names, "tactical", model=model)).status == "approved"
        assert model.calls == 1

    asyncio.run(go())


def test_semantic_budget_denial_and_unknown_outcome_accounting(goal):
    from backend.services.budget import DailyTokenBudget

    moment, names, brief, drafts = goal

    class Broken:
        name = "broken"
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("usage unknown")

    async def go():
        model = Broken()
        empty = DailyTokenBudget(0)
        verdict = await verify_with_model(drafts["tactical", "en"], brief, moment, names, "tactical", model=model, budget=empty)
        assert verdict.status == "rejected" and model.calls == 0
        budget = DailyTokenBudget(100000)
        verdict = await verify_with_model(drafts["tactical", "en"], brief, moment, names, "tactical", model=model, budget=budget)
        assert verdict.status == "rejected" and model.calls == 1
        assert budget.used > 1000 and budget.reserved == 0

    asyncio.run(go())


def test_all_demo_milestone_templates_pass_code_verification(derby):
    from backend.analytics.evidence import MatchEvidence

    names = NameAllowlist(derby.metadata)
    evidence = MatchEvidence(derby.metadata, derby.events, derby.frames)
    milestones = [m for m in evidence.moments if m.type == "player_milestone"]
    assert milestones
    for moment in milestones:
        for overlay in template_overlays(moment, names):
            verdict = verify(overlay.model_dump(), brief_from_moment(moment), moment, names, overlay.persona)
            assert verdict.status == "approved", (overlay, verdict)


def test_semantic_timeout_and_malformed_response_reject(goal):
    moment, names, brief, drafts = goal

    class Broken:
        name = "broken"

        async def complete(self, *args, **kwargs):
            return 'not json', 0

    class Slow:
        name = "slow"

        async def complete(self, *args, **kwargs):
            await asyncio.sleep(1)
            raise AssertionError("should time out")

    async def go():
        from backend.services.budget import DailyTokenBudget

        for model in (Broken(), Slow()):
            verdict = await verify_with_model(drafts["tactical", "en"], brief, moment, names, "tactical", model=model,
                                              budget=DailyTokenBudget(10000), timeout_s=0.01)
            assert verdict.status == "rejected" and verdict.reason_code == "SCHEMA"

    asyncio.run(go())


def test_breakit_does_not_mutate_input_and_invents_a_number(goal):
    moment, names, brief, drafts = goal
    draft = drafts["tactical", "en"]
    before = json.dumps(draft)
    bad = make_adversarial_draft(draft)
    assert json.dumps(draft) == before and bad != draft
    assert verify(bad, brief, moment, names, "tactical").reason_code == "NUMBER_NOT_IN_EVIDENCE"


def test_breakit_end_to_end_and_bad_input(derby, monkeypatch):
    from backend.agents import breakit

    class Library:
        async def get(self, match_id):
            assert match_id == "match_001"
            return derby

    monkeypatch.setattr(breakit, "_library", Library())

    async def go():
        result = await run_break_it("match_001", None, "tactical", "en")
        assert result["verdict"]["reason_code"] == "NUMBER_NOT_IN_EVIDENCE"
        fallback = Overlay.model_validate(result["repaired_or_fallback_overlay"])
        assert fallback.verification_status == "fallback" and fallback.source == "template"
        assert fallback.moment_id == "mom_044"
        ar = await run_break_it("match_001", fallback.moment_id, "player", "ar")
        assert ar["verdict"]["reason_code"] == "NUMBER_NOT_IN_EVIDENCE"
        assert ar["repaired_or_fallback_overlay"]["dir"] == "rtl"
        with pytest.raises(ValueError):
            await run_break_it("match_001", fallback.moment_id, "metric", "en")
        with pytest.raises(KeyError):
            await run_break_it("match_001", "mom_999999", "tactical", "en")

    asyncio.run(go())
