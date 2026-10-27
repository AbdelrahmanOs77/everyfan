"""New foundations retain existing possession semantics and causal cutoffs."""

import pytest

from backend.analytics.engine import MatchAnalytics
from backend.analytics.possession_index import PossessionIndex
from tests.test_agents_advanced_stats import event


def test_possession_duplicate_times_and_no_future():
    changes = [event(1, 0, "kickoff", outcome=None),
               event(2, 10, "possession_change", team="delta_utd", outcome=None),
               event(3, 10, "possession_change", outcome=None),
               event(4, 20, "possession_change", team="delta_utd", outcome=None)]
    index = PossessionIndex(changes)
    assert index.team_in_possession(-1) is None
    assert index.team_in_possession(10) == "nile_fc"
    assert index.durations(15) == {"nile_fc": 15, "delta_utd": 0}
    assert index.team_in_possession(19) == PossessionIndex(changes[:-1]).team_in_possession(19)


@pytest.mark.parametrize("at,window", [(100, 60), (2700, 900), (3784, 300), (5400, 5400)])
def test_possession_index_agrees_with_engine(derby, at, window):
    index, engine = PossessionIndex(derby.events), MatchAnalytics(derby.metadata)
    for e in derby.events:
        if e.game_time_s <= at:
            engine.add(e)
    durations = index.durations(at, window)
    for team in (derby.metadata.home.team_id, derby.metadata.away.team_id):
        assert durations[team] / sum(durations.values()) == pytest.approx(engine.possession_share(team, window, at))
