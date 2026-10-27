import pytest

from backend.analytics.evidence import MatchEvidence
from backend.analytics.geometry import area, formation, hull
from backend.analytics.live_tactics import tactical_snapshot
from tests.test_agents_tracking_metrics import frame, point
from tests.test_agents_advanced_stats import event


@pytest.mark.parametrize("counts", [(4, 4, 2), (4, 3, 3), (3, 5, 2), (5, 3, 2), (4, 2, 3, 1)])
@pytest.mark.parametrize("home", [True, False])
def test_formation_lines_are_direction_and_order_independent(counts, home):
    points = []
    for line, count in enumerate(counts):
        for n in range(count):
            depth = 20 + line * 25
            points.append((f"p{line}_{n}", depth if home else 105 - depth, 5 + n * 10))
    result = formation(points, home, 105)
    assert result["label"] == "-".join(map(str, counts))
    assert result == formation(points[::-1], home, 105)


def test_hull_area_is_exact_with_interior_and_duplicate_points():
    assert area(hull([(0, 0), (10, 0), (10, 5), (0, 5), (5, 2), (0, 0)])) == 50


def test_symmetric_space_ties_and_no_future(derby):
    ev = MatchEvidence(derby.metadata, [], [frame(0, [point("nil_06", "nile_fc", 20), point("del_06", "delta_utd", 85)])])
    data = tactical_snapshot(ev, 0, 60)
    h, a = (data["teams"][t]["control"]["current"] for t in ("nile_fc", "delta_utd"))
    assert h["whole_pct"] == a["whole_pct"]
    assert h["opponent_half_pct"] == a["opponent_half_pct"]
    assert h["whole_pct"] + a["whole_pct"] < 100  # centre-column ties belong to neither team.
    extended = MatchEvidence(derby.metadata, [], [frame(0, [point("nil_06", "nile_fc", 20), point("del_06", "delta_utd", 85)]),
                                               frame(1, [point("nil_06", "nile_fc", 90)])])
    assert data == tactical_snapshot(extended, 0, 60)


def test_counter_chain_and_directional_line_breaking(derby):
    frames = [frame(0, [point("nil_06", "nile_fc", 20), *[point(f"del_{n:02}", "delta_utd", x) for n, x in zip((2, 3, 4, 5), (40, 50, 60, 70))]])]
    events = [event(1, 0, "recovery", start=(20, 34), outcome=None), event(2, .1, start=(20, 34), end=(80, 34)),
              event(3, 8, "shot", start=(90, 34), outcome="saved")]
    ev = MatchEvidence(derby.metadata, events, frames)
    early = tactical_snapshot(ev, 1, 60, include_space=False)["teams"]["nile_fc"]
    assert early["line_breaking"]["count"] == 1
    assert early["line_breaking"]["passes"][0]["players_bypassed"] == 4
    assert early["counters"]["count"] == 0
    later = tactical_snapshot(ev, 9, 60, include_space=False)["teams"]["nile_fc"]
    assert later["counters"]["count"] == later["counters"]["fast_breaks"] == 1
    assert later["counters"]["items"][0]["evidence_event_ids"] == [e.event_id for e in events]


@pytest.mark.parametrize("home", [True, False])
def test_directional_pass_skip_pressing_and_opponent_possession_cancel(derby, home):
    tid, opp = ("nile_fc", "delta_utd") if home else ("delta_utd", "nile_fc")
    actor, rivals = ("nil_06", ["del_02", "del_04", "del_05"]) if home else ("del_06", ["nil_02", "nil_04", "nil_05"])
    x = lambda depth: depth if home else 105 - depth
    frames = [frame(0, [point(actor, tid, x(20)), *[point(pid, opp, x(depth)) for pid, depth in zip(rivals, (40, 50, 60))]])]
    events = [event(1, 0, "recovery", team=tid, player=actor, start=(x(20), 34), outcome=None),
              event(2, .1, team=tid, player=actor, start=(x(20), 34), end=(x(80), 34)),
              event(3, .2, "pressure", team=tid, player=actor, start=(x(80), 34), outcome=None),
              event(4, 1, "possession_change", team=opp, outcome=None),
              event(5, 5, "shot", team=tid, player=actor, outcome="saved"),
              event(6, 10, team=tid, player=actor, start=(x(20), 34), end=(x(80), 34))]
    ev = MatchEvidence(derby.metadata, events, frames)
    data = tactical_snapshot(ev, 20, 60, include_space=False)["teams"][tid]
    assert data["line_breaking"]["count"] == 1
    assert data["line_breaking"]["skipped"] == 1
    assert data["counters"]["count"] == 0
    assert data["pressing"]["cells"][0]["column"] == 4
    truncated = MatchEvidence(derby.metadata, events[:3], frames)
    assert tactical_snapshot(ev, .2, 60, include_space=False) == tactical_snapshot(truncated, .2, 60, include_space=False)
