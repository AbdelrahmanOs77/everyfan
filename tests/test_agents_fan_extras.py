"""Evidence-backed fan extras: independent arithmetic, cutoff and API checks."""

import math

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.analytics.evidence import MatchEvidence
from shared.schemas import Moment, TrackingFrame
from tests.test_agents_advanced_stats import event


def frame(n, t, points):
    return TrackingFrame(match_id="match_001", frame=n, game_clock_s=t, period=1,
                         ball={"x_m": 50, "y_m": 34},
                         players=[{"player_id": pid, "team_id": "nile_fc", "x_m": x, "y_m": y}
                                  for pid, x, y in points])


@pytest.fixture
def small(derby):
    frames = [frame(n, n / 2, [("nil_06", 10 + n * 3, 20), ("nil_10", 40 + n, 30)])
              for n in range(7)]
    events = [event(1, 0, "kickoff", outcome=None), event(2, 1),
              event(3, 2, kind="shot", receiver=None, outcome="saved"), event(4, 3)]
    return MatchEvidence(derby.metadata, events, frames)


def test_tracking_average_is_sample_mean_with_open_left_boundary(small):
    from backend.analytics.fan_extras import fan_stats
    data = fan_stats(small, at_s=2, window_s=1)
    dot = data["teams"]["nile_fc"]["average_positions"][0]
    assert dot["player_id"] == "nil_06"
    assert (dot["x_m"], dot["y_m"], dot["sample_count"]) == (20.5, 20, 2)
    assert (dot["first_frame"], dot["last_frame"]) == (3, 4)
    assert "tracking" in data["definitions"]["average_positions"]


def test_leaderboards_use_existing_tracker_and_exclude_future(small):
    from backend.analytics.fan_extras import fan_stats
    data = fan_stats(small, at_s=2, window_s=300)
    leaders = data["teams"]["nile_fc"]["leaderboards"]
    assert [r["player_id"] for r in leaders["distance_km"]] == ["nil_06", "nil_10"]
    assert leaders["distance_km"][0]["value"] == 0.01  # 4 steps * 3m, rounded to km.
    assert leaders["top_speed_kmh"][0]["value"] == 21.6  # 3m / .5s * 3.6.
    for metric, rows in leaders.items():
        for row in rows:
            assert row["value"] == small.player_stats(row["player_id"], 2)[metric]
            assert row["tracking_until_s"] <= 2
    before = fan_stats(small, at_s=1.49, window_s=300)
    assert before["teams"]["nile_fc"]["leaderboards"]["top_speed_kmh"][0]["value"] == 0


def test_tracking_sources_are_paginated_complete_and_time_bounded(small):
    first = small.tracking_samples("nil_06", at_s=2, window_s=1, offset=0, limit=1)
    second = small.tracking_samples("nil_06", at_s=2, window_s=1, offset=1, limit=1)
    assert first["total"] == 2
    assert first["next_offset"] == 1
    assert second["next_offset"] is None
    assert first["samples"][0] == {"frame": 3, "period": 1, "at_s": 1.5, "x_m": 19, "y_m": 20}
    assert second["samples"][0]["frame"] == 4
    assert small.tracking_samples("unknown", 2, 1) is None


@pytest.mark.parametrize("controls,momentum,status,leader", [
    ((60, 40), (5, 3), "leading", "home"),
    ((40, 60), (3, 5), "leading", "away"),
    ((60, 40), (3, 5), "mixed", None),
    ((60, 40), (3, 3), "mixed", None),
    ((None, 40), (5, 3), "insufficient", None),
])
def test_beginner_only_names_leader_when_both_measures_agree(controls, momentum, status, leader):
    from backend.analytics.fan_extras import on_top
    teams = {tid: {"control_index_last_5": controls[i], "momentum": momentum[i]}
             for i, tid in enumerate(("home", "away"))}
    assert on_top(teams) == {"status": status, "team_id": leader}


def test_momentum_chart_uses_configured_decay_and_full_event_evidence(small):
    from backend.analytics.fan_extras import fan_stats
    data = fan_stats(small, at_s=70, window_s=60)
    assert [p["at_s"] for p in data["momentum_timeline"]] == [0, 60, 70]
    last = data["momentum_timeline"][-1]
    weights = small.cfg["metrics"]["momentum"]["weights"]
    expected = weights["shot"] * math.exp(-(70 - 2) / 120)
    # Passes end in the attacking third and also contribute.
    expected += weights["final_third_pass"] * (math.exp(-(70 - 1) / 120) + math.exp(-(70 - 3) / 120))
    assert last["teams"]["nile_fc"]["value"] == round(expected, 1)
    assert set(last["teams"]["nile_fc"]["evidence_event_ids"]) == {"evt_00002", "evt_00003", "evt_00004"}
    assert last["teams"]["delta_utd"] == {"value": 0, "evidence_event_ids": []}


def test_club_cards_select_three_important_known_moments_and_match_ppda(small):
    from backend.analytics.fan_extras import fan_stats
    small.moments = [Moment(moment_id=f"mom_{i:03}", match_id="match_001", game_clock_s=i,
                            type="goal", team_id="nile_fc", importance=importance,
                            evidence_event_ids=["evt_00002"], verified_facts={}, rule_id="goal")
                     for i, importance in [(1, .5), (2, .9), (3, .7), (4, .8), (5, 1)]]
    team = fan_stats(small, at_s=4, window_s=300)["teams"]["nile_fc"]
    assert [m["moment_id"] for m in team["key_moments"]] == ["mom_002", "mom_004", "mom_003"]
    assert team["summary"]["ppda_match"] == small.state_at(4)["teams"]["nile_fc"]["ppda_match"]


def test_no_tracking_is_an_empty_state_and_future_data_cannot_change_result(small):
    from backend.analytics.fan_extras import fan_stats
    past = MatchEvidence(small.meta, [e for e in small.events if e.game_time_s <= 2],
                         [frame(n, n / 2, [("nil_06", 10 + n * 3, 20), ("nil_10", 40 + n, 30)])
                          for n in range(5)])
    assert fan_stats(past, at_s=2) == fan_stats(small, at_s=2)
    empty = MatchEvidence(small.meta, [], [])
    team = fan_stats(empty, at_s=0)["teams"]["nile_fc"]
    assert team["average_positions"] == []
    assert team["leaderboards"]["distance_km"] == []


def test_fractional_tracking_never_leaks_before_its_real_timestamp(derby):
    from backend.analytics.fan_extras import fan_stats
    ev = MatchEvidence(derby.metadata, [], [frame(0, .5, [("nil_06", 10, 20)])])
    assert fan_stats(ev, at_s=.4)["teams"]["nile_fc"]["leaderboards"]["distance_km"] == []
    assert fan_stats(ev, at_s=.5)["teams"]["nile_fc"]["leaderboards"]["distance_km"][0]["value"] == 0


def test_match_tracking_includes_kickoff_and_inactive_players_are_not_averaged(small):
    from backend.analytics.fan_extras import fan_stats
    assert small.tracking_samples("nil_06", at_s=5400, window_s=5400)["total"] == 7
    assert fan_stats(small, at_s=10, window_s=1)["teams"]["nile_fc"]["average_positions"] == []
    # A player's completed workload is still a valid match-to-date leaderboard entry.
    assert len(fan_stats(small, at_s=10)["teams"]["nile_fc"]["leaderboards"]["distance_km"]) == 2


def test_leaderboard_is_top_five_with_stable_ties(derby):
    from backend.analytics.fan_extras import fan_stats
    ids = [p.player_id for p in derby.metadata.home.players[:8]]
    ev = MatchEvidence(derby.metadata, [], [frame(0, 0, [(pid, 10, 20) for pid in reversed(ids)])])
    rows = fan_stats(ev, at_s=0)["teams"]["nile_fc"]["leaderboards"]["distance_km"]
    assert [r["player_id"] for r in rows] == sorted(ids)[:5]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]


def test_fan_and_tracking_endpoints_validate_bounds_and_unknown_players(small, monkeypatch):
    import backend.analytics.api as api

    async def evidence(_request, match_id):
        if match_id != "match_001":
            raise HTTPException(404, "unknown match")
        return small

    monkeypatch.setattr(api, "get_match_evidence", evidence)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        base = "/api/matches/match_001"
        assert client.get(base + "/fan-stats", params={"at_s": 2}).status_code == 200
        route = base + "/players/nil_06/tracking-samples"
        assert client.get(route, params={"at_s": 2, "limit": 1}).json()["total"] == 5
        for params in ({"at_s": -1}, {"at_s": 5401}, {"limit": 1001}, {"offset": -1}, {"window_s": 0}):
            assert client.get(route, params=params).status_code == 422
        assert client.get(base + "/fan-stats?window_s=0").status_code == 422
        assert client.get(base + "/players/unknown/tracking-samples").status_code == 404
        assert client.get("/api/matches/unknown/fan-stats").status_code == 404
