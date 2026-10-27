"""Compact source samples and prefix sums; no second copy of Pydantic frames."""

from array import array
from bisect import bisect_right


class PlayerPositions:
    def __init__(self):
        self.times, self.frames, self.periods = array("d"), array("i"), array("b")
        self.x, self.y = array("d"), array("d")
        self.sum_x, self.sum_y = array("d", [0]), array("d", [0])

    def append(self, frame, point):
        self.times.append(frame.game_clock_s)
        self.frames.append(frame.frame)
        self.periods.append(frame.period)
        self.x.append(point.x_m)
        self.y.append(point.y_m)
        self.sum_x.append(self.sum_x[-1] + point.x_m)
        self.sum_y.append(self.sum_y[-1] + point.y_m)

    def bounds(self, at_s, window_s):
        lo = 0 if window_s == 5400 else bisect_right(self.times, at_s - window_s)
        return lo, bisect_right(self.times, at_s)

    def average(self, at_s, window_s):
        lo, hi = self.bounds(at_s, window_s)
        if hi == lo:
            return None
        return {"x_m": round((self.sum_x[hi] - self.sum_x[lo]) / (hi - lo), 2),
                "y_m": round((self.sum_y[hi] - self.sum_y[lo]) / (hi - lo), 2),
                "sample_count": hi - lo, "first_frame": self.frames[lo], "last_frame": self.frames[hi - 1]}

    def samples(self, at_s, window_s, offset, limit):
        lo, hi = self.bounds(at_s, window_s)
        start, end = min(lo + offset, hi), min(lo + offset + limit, hi)
        return {"total": hi - lo, "offset": offset,
                "next_offset": offset + limit if end < hi else None,
                "samples": [{"frame": self.frames[i], "period": self.periods[i], "at_s": self.times[i],
                             "x_m": self.x[i], "y_m": self.y[i]} for i in range(start, end)]}
