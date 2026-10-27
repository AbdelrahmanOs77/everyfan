import pytest

from backend.analytics.evidence import MatchEvidence
from backend.analytics.player_profile import PlayerProfiles, percentile, player_profile
from tests.test_agents_advanced_stats import event
from tests.test_agents_tracking_metrics import frame, point


def test_midrank_ties_and_single_peer():
    assert percentile(10, [5, 10, 10, 15]) == 50
    assert percentile(10, [10]) == 50
    assert percentile(5, [10]) == 0
    assert percentile(15, [10]) == 100
    assert percentile(10, []) is None


def test_minutes_substitutions_red_cards_and_no_future(derby):
    starter = next(p for p in derby.metadata.home.players if p.starter and p.position != "GK")
    incoming = next(p for p in derby.metadata.home.players if not p.starter)
    events = [event(1, 600, "substitution", player=starter.player_id, receiver=incoming.player_id, outcome=None),
              event(2, 1200, "card", player=incoming.player_id, outcome="red")]
    ev = MatchEvidence(derby.metadata, events, [])
    profiles = PlayerProfiles(ev)
    assert profiles.minutes(starter.player_id, 1800) == 10
    assert profiles.minutes(incoming.player_id, 900) == 5
    assert profiles.minutes(incoming.player_id, 1800) == 10
    assert profiles.minutes(incoming.player_id, 900) == PlayerProfiles(MatchEvidence(derby.metadata, events[:1], [])).minutes(incoming.player_id, 900)


def test_reference_excludes_current_match_and_rates_stay_in_natural_units(derby):
    ev = MatchEvidence(derby.metadata, [event(1, 10)], [])
    group = ev.cfg["advanced_features"]["position_groups"][ev.players["nil_06"].position]
    peers = [{"match_id": mid, "player_id": "peer", "group": group, "minutes_played": 90,
              "values": {"passes_completed": value, "pass_accuracy_pct": 50}} for mid, value in [("match_001", 100), ("match_002", 3)]]
    result = player_profile(ev, "nil_06", 1800, reference=peers, sections=["benchmark", "role_index"])
    assert result["benchmark"]["peer_ids"] == ["match_002:peer"]
    rows = {r["metric"]: r for r in result["benchmark"]["rows"]}
    assert rows["passes_completed"]["value"] == 3
    assert rows["pass_accuracy_pct"]["value"] == 100
    assert player_profile(ev, "nil_06", 600, reference=peers, sections=["role_index"])["role_index"]["value"] is None


def test_heatmap_sums_sprints_equal_existing_count_and_no_future(derby):
    frames = [frame(n, [point("nil_06", "nile_fc", 10 + 4 * n)]) for n in range(9)]
    ev = MatchEvidence(derby.metadata, [], frames)
    data = player_profile(ev, "nil_06", 3, 300, sections=["heatmap", "trail", "sprints", "fatigue", "off_ball_runs"])
    assert sum(c["count"] for c in data["heatmap"]["cells"]) == data["heatmap"]["sample_count"]
    assert len(data["sprints"]) == ev.tracking.window(3, 300)["players"]["nil_06"]["sprints"] == 1
    past = MatchEvidence(derby.metadata, [], frames[:7])
    assert data == player_profile(past, "nil_06", 3, 300, sections=["heatmap", "trail", "sprints", "fatigue", "off_ball_runs"])


@pytest.mark.parametrize("tid,pid,home", [("nile_fc", "nil_06", True), ("delta_utd", "del_06", False)])
def test_off_ball_runs_respect_both_directions(derby, tid, pid, home):
    events = [event(1, 0, "kickoff", team=tid, player=pid, outcome=None)]
    frames = [frame(n, [point(pid, tid, 10 + n * 4 if home else 95 - n * 4, 10)]) for n in range(10)]
    ev = MatchEvidence(derby.metadata, events, frames)
    data = player_profile(ev, pid, 4.5, sections=["off_ball_runs"])
    assert data["off_ball_runs"]["count"] == 1
    assert data["off_ball_runs"]["items"][0]["depth_gain_m"] > 10


def test_matchup_uses_only_shared_frames(derby):
    frames = [frame(0, [point("nil_06", "nile_fc", 20), point("del_06", "delta_utd", 22)]),
              frame(1, [point("nil_06", "nile_fc", 80)])]
    data = player_profile(MatchEvidence(derby.metadata, [], frames), "nil_06", .5, sections=["matchup"])
    assert data["matchup"]["shared_frames"] == 1
    assert data["matchup"]["mean_distance_m"] == 2
    assert data["matchup"]["duels_won"] == 0


def test_output_block_hand_calculation_and_role_weighted_midrank(derby):
    frames = [frame(n, [point("nil_06", "nile_fc", 10 + 2 * n)]) for n in range(5)]
    ev = MatchEvidence(derby.metadata, [event(1, 1)], frames)
    block = player_profile(ev, "nil_06", 2, sections=["fatigue"])["fatigue"][0]
    assert block["distance_per_min_m"] == 240  # eight metres / (two seconds / 60).
    assert block["high_intensity_per_min_m"] == 0
    assert block["sprints"] == 0
    assert block["first_block_pct"] == 100
    profiles = ev.profiles
    own = profiles.metrics("nil_06", 1800)
    rates = ev.cfg["advanced_features"]["benchmark_rates"]
    values = {k: value if k in rates or value is None else value * 3 for k, value in own["values"].items()}
    group = profiles.cfg["position_groups"][ev.players["nil_06"].position]
    peer = {"match_id": "other", "player_id": "peer", "group": group, "minutes_played": 90, "values": values}
    benchmark, role = profiles.benchmark("nil_06", 1800, [peer])
    assert benchmark["reliable"]
    assert role["value"] == 5
    assert sum(p["contribution"] for p in role["parts"]) == pytest.approx(5, abs=.002)


def test_matchup_qualifier_opponents_are_symmetric(derby):
    frames = [frame(0, [point("nil_06", "nile_fc", 20), point("del_06", "delta_utd", 22)])]
    events = [event(1, 1, "duel", receiver="del_06", outcome="won"),
              event(2, 2, "duel", team="delta_utd", player="del_06", receiver=None, outcome="lost").model_copy(update={"qualifiers": {"opponent_id": "nil_06"}}),
              event(3, 3, "duel", team="delta_utd", player="del_06", receiver=None, outcome="won").model_copy(update={"qualifiers": {"opponent_player_id": "nil_06"}})]
    ev = MatchEvidence(derby.metadata, events, frames)
    home = player_profile(ev, "nil_06", 5, sections=["matchup"])["matchup"]
    away = player_profile(ev, "del_06", 5, sections=["matchup"])["matchup"]
    assert (home["duels_won"], home["duels_lost"]) == (2, 1)
    assert (away["duels_won"], away["duels_lost"]) == (1, 2)
