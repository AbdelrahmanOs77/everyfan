"""Compact per-frame positions, speed evidence and causal possession, indexed once."""

from array import array
from bisect import bisect_right

from .advanced import _frame_range
from .possession_index import PossessionIndex


class TacticsIndex:
    def __init__(self, meta, events):
        self.meta, self.possession = meta, PossessionIndex(events)
        self.players = {p.player_id: p for t in (meta.home, meta.away) for p in t.players}
        self.ids = sorted(self.players)
        self.columns = {pid: i for i, pid in enumerate(self.ids)}
        self.times, self.frames, self.periods = array("d"), array("i"), array("b")
        self.xy, self.speed, self.step, self.ball = array("f"), array("f"), array("f"), array("f")
        self.owner = []
        self._array = None

    def append(self, frame, tracker):
        self.times.append(frame.game_clock_s)
        self.frames.append(frame.frame)
        self.periods.append(frame.period)
        self.ball.extend((frame.ball.x_m, frame.ball.y_m))
        self.owner.append(self.possession.team_in_possession(frame.game_clock_s))
        by_id = {p.player_id: p for p in frame.players}
        for pid in self.ids:
            p, tr = by_id.get(pid), tracker.tracks.get(pid)
            self.xy.extend((p.x_m, p.y_m) if p else (float("nan"), float("nan")))
            self.speed.append(tr.smoothed_speed_kmh if p and tr and tr.smoothed_speed_kmh is not None else float("nan"))
            self.step.append(tr.step_distance_m if p and tr and tr.step_distance_m is not None else float("nan"))

    @property
    def positions(self):
        import numpy as np
        if self._array is None:
            self._array = np.asarray(self.xy).reshape(len(self.times), len(self.ids), 2)
        return self._array

    def bounds(self, at, window=5400):
        return (0 if window == 5400 else bisect_right(self.times, at - window)), bisect_right(self.times, at)

    def evidence(self, at, window=5400):
        return _frame_range(self.times, self.frames, *self.bounds(at, window))

    def nearest(self, at, tolerance=.5):
        """Nearest already-known sample; a later tracking frame is never consulted."""
        i = bisect_right(self.times, at) - 1
        return i if i >= 0 and at - self.times[i] <= tolerance else None

    def team_columns(self, team, outfield=True):
        return [self.columns[pid] for pid in self.ids if self.players[pid].team_id == team
                and (not outfield or self.players[pid].position != "GK")]
