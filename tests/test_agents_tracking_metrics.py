"""Hand-calculated windowed shape/intensity, direction and causal evidence tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.analytics.advanced import advanced_stats
from backend.analytics.config import load_config
from backend.analytics.evidence import MatchEvidence
from backend.analytics.fan_extras import fan_stats
from shared.schemas import TrackingFrame


def frame(n, points, *, at=None, period=1):
    return TrackingFrame(match_id="match_001", frame=n, game_clock_s=n / 2 if at is None else at,
                         period=period, ball={"x_m": 50, "y_m": 34}, players=points)


def point(pid, tid, x, y=34):
    return {"player_id": pid, "team_id": tid, "x_m": x, "y_m": y}


def movement(meta, *, step=4, count=9, cfg=None):
    frames = [frame(n, [point("nil_06", meta.home.team_id, 10 + step * n),
                        point("del_06", meta.away.team_id, 95 - step * n)]) for n in range(count)]
    return MatchEvidence(meta, [], frames, cfg)


def tracking(ev, *, at=4, window=300):
    return advanced_stats(ev.meta, ev.events, at_s=at, window_s=window,
                          cfg=ev.cfg, tracking_index=ev.tracking)["tracking"]


def test_team_shape_excludes_keeper_and_uses_own_goal_for_both_directions(derby):
    home, away = derby.metadata.home, derby.metadata.away
    hids = [p.player_id for p in home.players if p.position != "GK"][:5]
    aids = [p.player_id for p in away.players if p.position != "GK"][:5]
    hgk = next(p.player_id for p in home.players if p.position == "GK")
    agk = next(p.player_id for p in away.players if p.position == "GK")
    frames = []
    for n in range(3):
        # Home depths: 10,20,30,40,80 + n; away: 5,15,25,35,65 + 2n.
        points = [point(hgk, home.team_id, 0, 0), point(agk, away.team_id, 105, 68)]
        points += [point(pid, home.team_id, x + n, y)
                   for pid, x, y in zip(hids, (10, 20, 30, 40, 80), (10, 20, 30, 40, 50))]
        points += [point(pid, away.team_id, 105 - depth - 2 * n, y)
                   for pid, depth, y in zip(aids, (5, 15, 25, 35, 65), (15, 20, 25, 30, 35))]
        frames.append(frame(n, points))
    ev = MatchEvidence(derby.metadata, [], frames)
    result = tracking(ev, at=1, window=1)  # t=0 excluded; use .5 and 1.
    h, a = result["teams"][home.team_id], result["teams"][away.team_id]
    assert (h["mean_width_m"], h["mean_length_m"], h["defensive_line_height_m"]) == (40, 70, 26.5)
    assert (a["mean_width_m"], a["mean_length_m"], a["defensive_line_height_m"]) == (20, 60, 23)
    assert h["evidence"] == {"first_frame": 1, "last_frame": 2, "from_s": .5, "to_s": 1, "sample_count": 2}
    future = frame(3, [point(hids[0], home.team_id, 105, 68), point(aids[0], away.team_id, 0, 0)])
    extended = MatchEvidence(derby.metadata, [], frames + [future])
    assert result == tracking(extended, at=1, window=1)


def test_high_intensity_uses_smoothed_speeds_and_strict_sprint_duration(derby):
    ev = movement(derby.metadata)
    for at, expected_m, expected_sprints in [(1, None, None), (2, 8, 0), (2.5, 12, 1), (4, 24, 1)]:
        result = tracking(ev, at=at)
        for pid in ("nil_06", "del_06"):
            player = result["players"][pid]
            assert player["distance_above_threshold_m"] == expected_m
            assert player["sprints"] == expected_sprints
            assert player["evidence"]["to_s"] <= at
    window = tracking(ev, at=4, window=1)["players"]["nil_06"]
    assert (window["distance_above_threshold_m"], window["sprints"]) == (8, 0)
    assert window["window_evidence"]["first_frame"] == 7
    assert window["evidence"]["first_frame"] == 0  # Prior frames prove smoothing/continuity.


def test_distance_clips_first_segment_to_fractional_window(derby):
    ev = movement(derby.metadata)
    result = tracking(ev, at=2.5, window=.75)["players"]["nil_06"]
    assert result["distance_above_threshold_m"] == 6  # Half of 4m + full 4m.


@pytest.mark.parametrize("step,expected_distance,expected_sprints", [(2.75, 0, 0), (3.5, 21, 0), (4, 24, 1)])
def test_speed_thresholds_are_strict(derby, step, expected_distance, expected_sprints):
    ev = movement(derby.metadata, step=step)
    row = tracking(ev)["players"]["nil_06"]
    assert row["distance_above_threshold_m"] == expected_distance
    assert row["sprints"] == expected_sprints


def test_thresholds_are_read_from_configuration(derby):
    cfg = load_config()
    cfg["metrics"]["high_intensity"] = {"distance_threshold_kmh": 30, "sprint_threshold_kmh": 31,
                                          "sprint_min_duration_s": .25}
    result = tracking(movement(derby.metadata, cfg=cfg))
    assert result["players"]["nil_06"]["distance_above_threshold_m"] == 0
    assert result["players"]["nil_06"]["sprints"] == 0
    assert result["thresholds"]["distance_threshold_kmh"] == 30


def test_window_left_boundary_and_future_frames_cannot_change_results(derby):
    full = movement(derby.metadata)
    past = movement(derby.metadata, count=6)
    assert tracking(full, at=2.5) == tracking(past, at=2.5)
    assert tracking(full, at=2.49)["players"]["nil_06"]["sprints"] == 0
    assert tracking(full, at=3, window=.5)["players"]["nil_06"]["sprints"] == 0  # qualifying 2.5 excluded


@pytest.mark.parametrize("break_kind", ["gap", "half", "below_threshold"])
def test_sprints_restart_on_gaps_half_changes_and_low_speed(derby, break_kind):
    frames = [frame(n, [point("nil_06", "nile_fc", 10 + 4 * n)]) for n in range(5)]
    # Before interruption there are only two above-threshold samples (exactly 1s).
    if break_kind == "gap":
        frames += [frame(n, [point("nil_06", "nile_fc", 10 + 4 * n)]) for n in range(6, 12)]
    elif break_kind == "half":
        frames += [frame(n, [point("nil_06", "nile_fc", 10 + 4 * n)], period=2) for n in range(5, 11)]
    else:
        # Zero steps first lower the moving average, then the next run qualifies independently.
        xs = [26, 26, 26, 30, 34, 38, 42, 46]
        frames += [frame(n, [point("nil_06", "nile_fc", x)]) for n, x in enumerate(xs, 5)]
    ev = MatchEvidence(derby.metadata, [], frames)
    assert tracking(ev, at=frames[-2].game_clock_s)["players"]["nil_06"]["sprints"] == 0
    assert tracking(ev, at=frames[-1].game_clock_s)["players"]["nil_06"]["sprints"] == 1


def test_two_separate_sprints_are_counted_and_duration_is_configurable(derby):
    x, frames = 5, [frame(0, [point("nil_06", "nile_fc", 5)])]
    for n, step in enumerate([4] * 6 + [0] * 3 + [4] * 6, 1):
        x += step
        frames.append(frame(n, [point("nil_06", "nile_fc", x)]))
    ev = MatchEvidence(derby.metadata, [], frames)
    assert tracking(ev, at=7.5)["players"]["nil_06"]["sprints"] == 2
    assert tracking(ev, at=7.5, window=1)["players"]["nil_06"]["sprints"] == 1
    cfg = load_config()
    cfg["metrics"]["high_intensity"]["sprint_min_duration_s"] = .25
    assert tracking(movement(derby.metadata, cfg=cfg), at=1.5)["players"]["nil_06"]["sprints"] == 1


def test_missing_tracking_and_fewer_than_four_outfield_players_are_explicit(derby):
    empty = MatchEvidence(derby.metadata, [], [])
    data = tracking(empty)
    assert data["teams"]["nile_fc"]["mean_width_m"] is None
    assert data["players"]["nil_06"]["distance_above_threshold_m"] is None
    assert data["players"]["nil_06"]["evidence"] is None
    sparse = movement(derby.metadata)
    assert tracking(sparse)["teams"]["nile_fc"]["defensive_line_height_m"] is None


def test_both_endpoints_return_identical_selected_window_metrics_and_frame_ranges(derby, monkeypatch):
    import backend.analytics.api as api
    ev = movement(derby.metadata)

    async def evidence(_request, _match_id):
        return ev

    monkeypatch.setattr(api, "get_match_evidence", evidence)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        params = {"at_s": 3, "window_s": 1}
        a = client.get("/api/matches/match_001/advanced-stats", params=params)
        f = client.get("/api/matches/match_001/fan-stats", params=params)
        assert a.status_code == f.status_code == 200
        assert a.json()["tracking"] == f.json()["tracking"] == tracking(ev, at=3, window=1)
        assert f.json()["tracking"]["players"]["nil_06"]["sprints"] == 1
        assert fan_stats(ev, at_s=3, window_s=1)["tracking"]["at_s"] == 3
