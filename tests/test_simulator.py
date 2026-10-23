import hashlib

import pytest

from backend.simulator.generator import _jsonl, generate, list_scenarios, load_scenario
from backend.simulator.validator import validate_match


def _hashes(match):
    return (hashlib.sha256(_jsonl(match.events)).hexdigest(),
            hashlib.sha256(_jsonl(match.frames)).hexdigest())


def test_same_seed_gives_identical_output(derby):
    again = generate(load_scenario("derby_balanced"))
    assert _hashes(again) == _hashes(derby)


def test_different_seed_gives_different_match():
    spec = load_scenario("derby_balanced").model_copy(update={"seed": 1})
    assert _hashes(generate(spec)) != _hashes(generate(load_scenario("derby_balanced")))


@pytest.mark.parametrize("scenario_id", list_scenarios())
def test_every_scenario_passes_quality_validator(matches, scenario_id):
    m = matches[scenario_id]
    report = validate_match(m.metadata, m.events, m.frames)
    assert report.ok, report.errors[:10]


@pytest.mark.parametrize("scenario_id", list_scenarios())
def test_final_score_matches_script(matches, scenario_id):
    m = matches[scenario_id]
    scripted = {}
    for f in m.spec.forced_events:
        if f.type == "goal":
            scripted[f.team_id] = scripted.get(f.team_id, 0) + 1
    goals = {}
    for e in m.events:
        if e.type == "goal":
            goals[e.team_id] = goals.get(e.team_id, 0) + 1
    assert goals == scripted


def test_derby_story_beats(derby):
    goals = [(e.game_clock_s // 60, e.player_id) for e in derby.events if e.type == "goal"]
    assert goals == [(12, "nil_09"), (31, "del_10"), (49, "del_09"), (63, "nil_10")]
    rocket = next(e for e in derby.events if e.type == "shot" and e.outcome == "goal" and e.player_id == "nil_10")
    length = sum(((b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5 for a, b in zip(rocket.ball_path, rocket.ball_path[1:]))
    assert length / rocket.duration_s * 3.6 >= 100
    assert not any(e.type == "card" and e.outcome in ("red", "second_yellow") for e in derby.events)


def test_red_card_scenario_plays_with_ten(matches):
    m = matches["red_card_60"]
    red = next(e for e in m.events if e.type == "card" and e.outcome == "red")
    assert red.player_id == "nil_04" and red.game_clock_s // 60 == 60
    late = [f for f in m.frames if f.game_clock_s > red.game_time_s + 1]
    assert all(sum(p.team_id == "nile_fc" for p in f.players) == 10 for f in late)


def test_tracking_is_two_hertz_and_complete(derby):
    assert len(derby.frames) == 10801
    assert derby.frames[1].game_clock_s - derby.frames[0].game_clock_s == 0.5
    assert all(len(f.players) == 22 for f in derby.frames)


def test_realistic_match_totals(derby):
    passes = [e for e in derby.events if e.type == "pass"]
    shots = [e for e in derby.events if e.type == "shot"]
    accuracy = sum(e.outcome == "completed" for e in passes) / len(passes)
    assert 700 <= len(passes) <= 1300
    assert 0.7 <= accuracy <= 0.9
    assert 15 <= len(shots) <= 45
