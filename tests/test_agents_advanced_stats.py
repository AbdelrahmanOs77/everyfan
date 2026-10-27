"""Cross-owner C/D integration: new analytics stay deterministic and time bounded."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.analytics.config import load_config
from shared.schemas import SyntheticEvent


def event(n, time, kind="pass", team="nile_fc", player="nil_06", receiver="nil_10",
          start=(50, 34), end=(75, 34), outcome="completed"):
    return SyntheticEvent(event_id=f"evt_{n:05}", match_id="match_001", seq=n,
                          game_time_s=time, game_clock_s=int(time), period=1,
                          type=kind, team_id=team, player_id=player, receiver_id=receiver,
                          start_x_m=start[0], start_y_m=start[1], end_x_m=end[0], end_y_m=end[1],
                          outcome=outcome)


@pytest.fixture
def actions():
    return [event(1, 1, "kickoff", outcome=None),
            event(2, 10),  # Nile final-third entry, forward 25 m.
            event(3, 20, start=(75, 34), end=(95, 34)),  # One box entry.
            event(4, 30, kind="shot", start=(95, 34), end=(105, 34), outcome="saved", receiver=None),
            event(5, 40, team="delta_utd", player="del_06", receiver="del_10", start=(60, 30), end=(30, 30)),
            event(6, 50, start=(75, 34), end=(95, 34), outcome="intercepted"),
            event(7, 60, kind="duel", outcome="won", receiver=None),
            event(8, 70, kind="recovery", start=(80, 30), outcome=None, receiver=None),
            event(9, 200, kind="shot", start=(95, 34), end=(105, 34), outcome="goal", receiver=None)]


def advanced(meta, events, at=100, window=100):
    from backend.analytics.advanced import advanced_stats
    return advanced_stats(meta, events, at_s=at, window_s=window, cfg=load_config())


def test_advanced_metrics_are_hand_calculated_and_direction_aware(derby, actions):
    data = advanced(derby.metadata, actions)
    home, away = (data["teams"][t]["current"] for t in ("nile_fc", "delta_utd"))
    assert (home["passes"], home["passes_completed"]) == (3, 2)
    assert home["pass_accuracy_pct"] == 66.7
    assert home["forward_passes_10m"] == 2
    assert home["final_third_entries"] == away["final_third_entries"] == 1
    assert home["box_entries"] == 1
    assert (home["shots"], home["shots_on_target"]) == (1, 1)
    assert home["avg_shot_distance_m"] == 10
    assert home["duel_win_pct"] == 100
    assert home["high_recoveries"] == 1
    assert home["final_third_share_pct"] == 66.7
    assert away["final_third_share_pct"] == 33.3


def test_window_excludes_left_boundary_and_never_uses_future(derby, actions):
    data = advanced(derby.metadata, actions, at=50, window=30)
    assert data["teams"]["nile_fc"]["current"]["passes"] == 1  # 20 excluded, 50 included.
    assert data["teams"]["nile_fc"]["match"]["passes"] == 3
    assert "evt_00009" not in str(data)
    assert data == advanced(derby.metadata, actions + [event(10, 300)], at=50, window=30)


def test_network_and_maps_resolve_to_real_events(derby, actions):
    home = advanced(derby.metadata, actions)["teams"]["nile_fc"]
    assert home["pass_network"]["edges"] == [{"from_player_id": "nil_06", "to_player_id": "nil_10",
                                               "completed_passes": 2, "evidence_event_ids": ["evt_00002", "evt_00003"]}]
    assert home["shot_map"][0]["event_id"] == "evt_00004"
    assert home["shot_map"][0]["x_m"] == 95
    assert sum(cell["completed_passes"] for cell in home["territory"]) == 2
    assert set(home["evidence_event_ids"]) == {e.event_id for e in actions[:8] if e.team_id == "nile_fc"}


def test_missing_denominators_and_positions_are_not_fabricated(derby):
    data = advanced(derby.metadata, [], at=0, window=300)
    home = data["teams"]["nile_fc"]["current"]
    assert home["pass_accuracy_pct"] is None
    assert home["ppda"] is None
    assert home["shot_conversion_pct"] is None
    assert home["final_third_share_pct"] is None
    missing = event(1, 10, start=(None, None), end=(None, None))
    data = advanced(derby.metadata, [missing])
    assert data["teams"]["nile_fc"]["current"]["passes"] == 1
    assert data["teams"]["nile_fc"]["pass_network"]["nodes"] == []


def test_explicit_metric_definitions_and_comparison_deltas(derby, actions):
    data = advanced(derby.metadata, actions, at=100, window=60)
    team = data["teams"]["nile_fc"]
    assert team["deltas"]["pass_accuracy_pct"] == -66.7
    assert "10 m" in data["definitions"]["forward_passes_10m"]
    assert "completed passes" in data["definitions"]["final_third_share_pct"]
    assert data["definitions_version"] == "1.0"


def test_advanced_endpoint_validates_bounds_and_returns_snapshot(derby, actions, monkeypatch):
    import backend.analytics.api as api

    async def evidence(_request, match_id):
        if match_id != "match_001":
            raise HTTPException(404, "unknown match")
        return SimpleNamespace(meta=derby.metadata, events=actions, cfg=load_config())

    monkeypatch.setattr(api, "get_match_evidence", evidence)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        route = "/api/matches/match_001/advanced-stats"
        response = client.get(route, params={"at_s": 100, "window_s": 60})
        assert response.status_code == 200
        assert response.json()["at_s"] == 100
        assert client.get(route, params={"window_s": 0}).status_code == 422
        assert client.get(route, params={"at_s": 5401}).status_code == 422
        assert client.get("/api/matches/unknown/advanced-stats").status_code == 404


@pytest.mark.parametrize("scenario", ["derby_balanced", "late_comeback", "red_card_60", "press_vs_block"])
def test_new_dashboard_reconciles_with_existing_metrics_for_every_scenario(matches, scenario):
    from backend.analytics.engine import MatchAnalytics, r1

    match = matches[scenario]
    result = advanced(match.metadata, match.events, at=3784, window=300)
    original = MatchAnalytics(match.metadata)
    for item in match.events:
        if item.game_time_s <= 3784:
            original.add(item)
    original.now = 3784
    for tid in (match.metadata.home.team_id, match.metadata.away.team_id):
        actual = result["teams"][tid]["current"]
        assert actual["control_index"] == r1(original.control_index(tid, 300, 3784))
        assert actual["ppda"] == r1(original.ppda(tid, 300, 3784))
        assert actual["pass_accuracy_pct"] == r1(100 * original.pass_accuracy(tid, 300, 3784))
        assert actual["possession_pct"] == r1(100 * original.possession_share(tid, 300, 3784))
        source = {e.event_id for e in match.events if 3484 < e.game_time_s <= 3784 and e.team_id == tid}
        assert set(result["teams"][tid]["evidence_event_ids"]) == source
