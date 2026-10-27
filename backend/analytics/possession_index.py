"""Causal possession lookup using the existing kickoff/change attribution rule."""

from bisect import bisect_right


class PossessionIndex:
    def __init__(self, events):
        changes = sorted((e for e in events if e.type in ("kickoff", "possession_change") and e.team_id),
                         key=lambda e: (e.game_time_s, e.seq))
        self.times = [e.game_time_s for e in changes]
        self.teams = [e.team_id for e in changes]
        self.ids = [e.event_id for e in changes]

    def team_in_possession(self, at_s):
        i = bisect_right(self.times, at_s) - 1
        return self.teams[i] if i >= 0 else None

    def durations(self, at_s, window_s=5400):
        start, out = max(0, at_s - window_s), {}
        for i, (time, team) in enumerate(zip(self.times, self.teams)):
            if time > at_s:
                break
            end = min(at_s, self.times[i + 1] if i + 1 < len(self.times) else at_s)
            out[team] = out.get(team, 0) + max(0, end - max(time, start))
        return out

    def evidence(self, at_s, window_s=5400):
        lo = max(0, bisect_right(self.times, max(0, at_s - window_s)) - 1)
        return self.ids[lo:bisect_right(self.times, at_s)]
